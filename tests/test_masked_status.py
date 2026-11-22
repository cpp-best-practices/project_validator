"""Masked exit statuses (upstream #334): a command whose exit status its script throws away (`|| true`, a pipe
without pipefail, a sequence without `set -e`, a condition) cannot fail CI, so it is advisory, with the reason."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.code_formatting import code_formatting
from project_validator.core import Status
from project_validator.facts import Command
from project_validator.facts.exit_status import Shell, masked, shell_of
from project_validator.facts.shell import ShellCommand, split_script
from project_validator.facts.tools import ToolRun
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

POSIX = Shell()
ERREXIT = Shell(errexit=True)
STRICT = Shell(errexit=True, pipefail=True)
PYTHON = {"pyproject.toml": "[project]\nname = 'app'\n\n[tool.ruff]\nline-length = 100\n", "src/app.py": ""}


def _reasons(script: str, shell: Shell) -> list[tuple[str, str]]:
    commands = [found for found in split_script(script) if isinstance(found, ShellCommand)]
    return [(command.argv[0], reason) for command, reason in zip(commands, masked(commands, shell), strict=True)]


def _reason(script: str, shell: Shell, program: str = "pytest") -> str:
    return dict(_reasons(script, shell))[program]


class FallbackTests(unittest.TestCase):
    def test_a_fallback_that_succeeds_masks_the_failure(self) -> None:
        self.assertEqual(_reason("pytest || true", STRICT), "|| true")
        self.assertEqual(_reason("pytest || :", STRICT), "|| :")
        self.assertEqual(_reason("pytest || exit 0", STRICT), "|| exit 0")
        self.assertEqual(_reason('pytest || echo "tests failed"', STRICT), "|| echo tests failed")

    def test_a_long_fallback_is_named_by_its_program(self) -> None:
        self.assertEqual(_reason('pytest || echo "::warning::the tests failed, see the report"', STRICT), "|| echo …")

    def test_a_fallback_that_fails_again_keeps_the_failure(self) -> None:
        for script in (
            "pytest || exit 1",
            "pytest || exit",
            "pytest || exit $?",
            "pytest || false",
            "pytest || return 1",
            'pytest || { echo "tests failed"; exit 1; }',
            "pytest || (echo failed && false)",
        ):
            with self.subTest(script=script):
                self.assertEqual(_reason(script, STRICT), "")

    def test_a_fallback_that_tests_the_status_lets_only_what_it_accepts_through(self) -> None:
        """Zig's fuzzing runs until `timeout` stops it: `|| [ $? -eq 124 ]` accepts the timeout, and any other failure
        still fails."""
        for script in ("timeout 60 zig build fuzz || [ $? -eq 124 ]", "timeout 60 pytest || [[ $? == 124 ]]"):
            with self.subTest(script=script):
                self.assertEqual(_reasons(script, STRICT)[0][1], "")

    def test_a_fallback_group_that_goes_on_to_the_next_line_is_not_judged(self) -> None:
        self.assertEqual(_reason("pytest || {\n  echo failed\n  exit 1\n}", STRICT), "")

    def test_a_retry_masks_the_first_run_only(self) -> None:
        self.assertEqual(_reasons("pytest || pytest --lf", STRICT), [("pytest", "|| pytest --lf"), ("pytest", "")])


class PipeTests(unittest.TestCase):
    def test_without_pipefail_only_the_last_command_of_a_pipe_counts(self) -> None:
        self.assertEqual(
            _reasons("pytest | tee log", ERREXIT), [("pytest", "piped into tee without pipefail"), ("tee", "")]
        )
        self.assertEqual(_reason("pytest |& tee log", ERREXIT), "piped into tee without pipefail")

    def test_with_pipefail_every_command_of_a_pipe_counts(self) -> None:
        self.assertEqual(_reasons("pytest | tee log", STRICT), [("pytest", ""), ("tee", "")])

    def test_set_turns_pipefail_on_and_off(self) -> None:
        for script in ("set -o pipefail", "set -euo pipefail", "set -eo pipefail", "set -o errexit -o pipefail"):
            with self.subTest(script=script):
                self.assertEqual(_reason(f"{script}\npytest | tee log", ERREXIT), "")
        self.assertEqual(_reason("set +o pipefail\npytest | tee log", STRICT), "piped into tee without pipefail")

    def test_a_status_read_after_the_pipe_keeps_the_failure(self) -> None:
        self.assertEqual(_reason('pytest | tee log\nexit "${PIPESTATUS[0]}"', ERREXIT), "")


class SequenceTests(unittest.TestCase):
    def test_without_errexit_a_later_command_s_status_replaces_it(self) -> None:
        self.assertEqual(_reason("pytest; echo done", POSIX), "followed by other commands without set -e")
        self.assertEqual(_reason("pytest\necho done", POSIX), "followed by other commands without set -e")

    def test_without_errexit_the_last_command_and_its_list_count(self) -> None:
        self.assertEqual(_reasons("cd tests && pytest", POSIX), [("cd", ""), ("pytest", "")])
        self.assertEqual(_reason("echo start; pytest", POSIX), "")

    def test_with_errexit_every_command_counts(self) -> None:
        self.assertEqual(_reasons("pytest\necho done", ERREXIT), [("pytest", ""), ("echo", "")])

    def test_set_turns_errexit_on_and_off(self) -> None:
        self.assertEqual(
            _reason("set +e\npytest\nset -e\necho done", ERREXIT), "followed by other commands without set -e"
        )
        self.assertEqual(_reason("set -e\npytest\necho done", POSIX), "")
        self.assertEqual(_reason("set -o errexit\npytest\necho done", POSIX), "")

    def test_a_set_command_is_never_reported(self) -> None:
        """glib's scripts open with `set -eux -o pipefail`, which runs before errexit is on: what set does is the
        shell's options, not a step whose failure matters."""
        self.assertEqual(_reason("set -eux -o pipefail\npytest", POSIX, "set"), "")
        self.assertEqual(_reason("set +e\nset -e\npytest", ERREXIT, "set"), "")

    def test_with_errexit_a_command_before_and_in_the_middle_of_a_script_is_ignored(self) -> None:
        self.assertEqual(_reason("pytest && echo ok\necho next", ERREXIT), "before && in the middle of the script")
        self.assertEqual(_reason("echo first\npytest && echo ok", ERREXIT), "")

    def test_a_status_read_after_the_command_keeps_the_failure(self) -> None:
        self.assertEqual(_reason("pytest\nstatus=$?\necho done\nexit $status", POSIX), "")
        self.assertEqual(_reason("pytest; rc=$?; echo done; exit $rc", POSIX), "")
        self.assertEqual(_reason("pytest\nif [ $? -ne 0 ]; then exit 1; fi", POSIX), "")

    def test_a_command_in_the_background_is_no_gate(self) -> None:
        self.assertEqual(_reason("pytest &\nsleep 5", STRICT), "run in the background")


class ConditionTests(unittest.TestCase):
    def test_a_condition_selects_a_branch_and_is_no_gate(self) -> None:
        self.assertEqual(
            _reasons("if ruff check .; then echo ok; fi", STRICT), [("ruff", "an if condition"), ("echo", "")]
        )
        self.assertEqual(_reason("while pytest; do :; done", STRICT), "a while condition")
        self.assertEqual(_reason("until pytest; do :; done", STRICT), "an until condition")
        self.assertEqual(_reason("! pytest", STRICT), "negated by !")
        self.assertEqual(_reason("if [ -f x ]; then echo; elif pytest; then :; fi", STRICT), "an elif condition")

    def test_every_command_of_a_condition_list_is_a_condition(self) -> None:
        self.assertEqual(
            _reasons("if mypy . && pytest; then :; fi", STRICT),
            [("mypy", "an if condition"), ("pytest", "an if condition"), (":", "")],
        )


class NestedTests(unittest.TestCase):
    def test_a_command_substitution_s_commands_are_not_judged(self) -> None:
        self.assertEqual(_reasons("echo $(pytest)", STRICT), [("pytest", ""), ("echo", "")])


class ShellOfTests(unittest.TestCase):
    def test_a_shell_command_line_s_options(self) -> None:
        self.assertEqual(shell_of("bash --noprofile --norc -eo pipefail {0}"), STRICT)
        self.assertEqual(shell_of("bash -e {0}"), ERREXIT)
        self.assertEqual(shell_of("bash -l {0}"), POSIX)
        self.assertEqual(shell_of("bash -el {0}"), ERREXIT)
        self.assertEqual(shell_of("sh -c"), POSIX)

    def test_a_program_that_is_not_a_shell_has_no_options_to_read(self) -> None:
        self.assertIsNone(shell_of("msys2 {0}"))
        self.assertIsNone(shell_of("pwsh -command . '{0}'"))


def _workflow(*steps: Mapping[str, object], **job: object) -> dict[str, str]:
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"check": {"runs-on": "ubuntu-latest", "steps": steps, **job}}})}


def _advisory(files: dict[str, str]) -> dict[str, str]:
    with temp_project(files) as root:
        return {run.tool: run.advisory for run in make_context(root).facts.of(ToolRun)}


class GitHubTests(unittest.TestCase):
    def test_the_default_shell_has_errexit_but_no_pipefail(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check . | tee lint.log\nruff format --check .\necho done"})}
        self.assertEqual(_advisory(files), {"ruff check": "piped into tee without pipefail", "ruff format": ""})

    def test_an_explicit_bash_shell_has_pipefail(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check . | tee lint.log", "shell": "bash"})}
        self.assertEqual(_advisory(files), {"ruff check": ""})
        defaults = _workflow({"run": "ruff check . | tee lint.log"}, defaults={"run": {"shell": "bash"}})
        self.assertEqual(_advisory({**PYTHON, **defaults}), {"ruff check": ""})

    def test_a_shell_without_errexit_masks_all_but_the_last_command(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check .\necho done", "shell": "bash -l {0}"})}
        self.assertEqual(_advisory(files), {"ruff check": "followed by other commands without set -e"})

    def test_powershell_is_not_judged(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check . | Out-File lint.log", "shell": "pwsh"})}
        self.assertEqual(_advisory(files), {"ruff check": ""})

    def test_a_shell_an_expression_names_is_not_judged(self) -> None:
        step = {"run": "ruff check .\necho done", "shell": "bash ${{ vars.BASH_FLAGS }} {0}"}
        self.assertEqual(_advisory({**PYTHON, **_workflow(step)}), {"ruff check": ""})

    def test_continue_on_error_still_wins(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check . || true", "continue-on-error": True})}
        self.assertEqual(_advisory(files), {"ruff check": "continue-on-error"})

    def test_the_finding_says_why_the_run_cannot_fail(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff format --check . || true"})}
        with temp_project(files) as root:
            result = code_formatting.run(make_context(root))
        self.assertNotEqual(result.status, Status.PASS, result)
        self.assertIn("ruff format runs in CI but cannot fail it (|| true)", result.details, result)


class GitLabTests(unittest.TestCase):
    def _advisory(self, script: list[str], **job: object) -> list[str]:
        with temp_project({".gitlab-ci.yml": json.dumps({"check": {"script": script, **job}})}) as root:
            return [command.advisory for command in make_context(root).facts.of(Command) if not command.via]

    def test_gitlab_s_bash_has_errexit_and_pipefail(self) -> None:
        self.assertEqual(self._advisory(["ruff check . | tee lint.log"]), ["", ""])
        self.assertEqual(self._advisory(["ruff check . || true"]), ["|| true", ""])

    def test_the_lines_of_before_script_and_script_are_one_script(self) -> None:
        """GitLab Runner runs a job's before_script and script lines as one shell script: errexit passes over a
        failure before `&&` on any line but the last, which ends the script with its status."""
        middle = "before && in the middle of the script"
        self.assertEqual(self._advisory(["ruff check . && echo ok", "pytest"]), [middle, "", ""])
        self.assertEqual(self._advisory(["pytest", "ruff check . && echo ok"]), ["", "", ""])
        self.assertEqual(self._advisory(["pytest"], before_script=["ruff check . && echo ok"]), [middle, "", ""])

    def test_a_set_on_one_line_holds_for_the_lines_after_it(self) -> None:
        masked = "followed by other commands without set -e"
        self.assertEqual(self._advisory(["set +e", "ruff check .", "echo done"]), ["", masked, ""])
        self.assertEqual(self._advisory(["set +e", "set -e", "ruff check .", "echo done"])[2], "")

    def test_after_script_cannot_fail_the_job(self) -> None:
        """GitLab ignores the exit status of after_script, which runs in a shell of its own."""
        after = "in after_script, whose failure GitLab ignores"
        self.assertEqual(self._advisory(["pytest"], after_script=["ruff check .", "echo done"]), ["", after, after])


class ExpandedTests(unittest.TestCase):
    def test_a_make_recipe_line_is_a_shell_without_errexit(self) -> None:
        for recipe, reason in (
            ("ruff check .; echo done", "followed by other commands without set -e"),
            ("ruff check . && echo done", ""),
            ("-ruff check .", "make ignores its failure (-)"),
        ):
            with self.subTest(recipe=recipe):
                files = {**PYTHON, "Makefile": f"lint:\n\t{recipe}\n", **_workflow({"run": "make lint"})}
                self.assertEqual(_advisory(files)["ruff check"], reason)

    def test_a_just_recipe_line_after_a_dash_is_ignored(self) -> None:
        files = {**PYTHON, "justfile": "lint:\n    -ruff check .\n", **_workflow({"run": "just lint"})}
        self.assertEqual(_advisory(files)["ruff check"], "just ignores its failure (-)")

    def test_a_package_script_is_a_shell_without_errexit(self) -> None:
        package = {"name": "app", "scripts": {"lint": "eslint . || true"}, "devDependencies": {"eslint": "9"}}
        files = {"package.json": json.dumps(package), "index.js": "", **_workflow({"run": "npm run lint"})}
        self.assertEqual(_advisory(files)["eslint"], "|| true")

    def test_a_shell_script_file_s_options_come_from_the_shell_that_runs_it(self) -> None:
        masking = "followed by other commands without set -e"
        for script, run, reason in (
            ("#!/bin/bash\nruff check .\necho done\n", "./ci/lint.sh", masking),
            ("#!/bin/bash -e\nruff check .\necho done\n", "./ci/lint.sh", ""),
            ("#!/usr/bin/env -S bash -e\nruff check .\necho done\n", "./ci/lint.sh", ""),
            ("#!/bin/bash -e\nruff check .\necho done\n", "bash ci/lint.sh", masking),
            ("ruff check .\necho done\n", "bash -e ci/lint.sh", ""),
            ("#!/usr/bin/env bash\nset -euo pipefail\nruff check . | tee log\n", "bash ci/lint.sh", ""),
            ("ruff check .\necho done\n", ". ci/lint.sh", ""),
        ):
            with self.subTest(script=script, run=run):
                files = {**PYTHON, "ci/lint.sh": script, **_workflow({"run": run})}
                self.assertEqual(_advisory(files)["ruff check"], reason)


if __name__ == "__main__":
    unittest.main()
