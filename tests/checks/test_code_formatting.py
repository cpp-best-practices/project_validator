import json
import unittest
from collections.abc import Mapping
from typing import ClassVar

from project_validator.checks.code_formatting import code_formatting
from project_validator.core import Options, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.facts import Facts
from project_validator.facts.formatting import FORMAT, Enforcement
from project_validator.facts.tools import ToolRun
from project_validator.policy.formatting import judge_formatting
from project_validator.questions import Answer
from project_validator.questions.tooling import tool_answer
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    ci_running,
    github_job,
    make_context,
    run_as,
    run_in_every_layout,
    temp_project,
)

ALLOW_UNKNOWN = Options(allow_unknown=True)
CLANG_FORMAT = {".clang-format": "BasedOnStyle: LLVM\n"}
REWRITES = "CI runs {} but only to rewrite files; nothing fails when they are not formatted"


def _uses(*steps: Mapping[str, object]) -> dict[str, str]:
    """A GitHub workflow whose job runs `steps` (`{"uses": ...}` or `{"run": ...}`)."""
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"format": {"runs-on": "ubuntu-latest", "steps": list(steps)}}})}


class CodeFormattingTests(unittest.TestCase):
    HINT = "consider a CI job that runs clang-format --dry-run -Werror"

    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_in_every_layout(self, code_formatting, files, options=options)

    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add formatters, so only the stable languages are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, code_formatting.languages)

    def test_fails_without_a_clang_format_file(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(
            result, Result.failed("no clang-format configuration found; formatting is not defined", self.HINT)
        )

    def test_passes_when_ci_checks_formatting(self) -> None:
        # The fixture runs `find ... | xargs clang-format --dry-run -Werror`.
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result, Result.passed(".clang-format is defined and CI runs clang-format"))

    def test_passes_with_a_clang_format_action(self) -> None:
        for action in ("DoozyX/clang-format-lint-action@v0.18", "jidicula/clang-format-action@v4.15.0"):
            with self.subTest(action=action):
                result = self._run({"_clang-format": "BasedOnStyle: LLVM\n", **_uses({"uses": action})})
                self.assertEqual(result, Result.passed("_clang-format is defined and CI runs clang-format"))

    def test_checking_commands_in_any_ci_pass(self) -> None:
        commands = (
            "git clang-format --diff origin/main",
            "clang-format-18 -n --Werror src/a.cpp",
            "run-clang-format.py -r src",
        )
        for provider in CI_FILES:
            for command in commands:
                with self.subTest(ci=provider, command=command):
                    result = self._run({**CLANG_FORMAT, **ci_running(provider, command)})
                    self.assertEqual(result.status, Status.PASS)

    def test_rewriting_files_enforces_nothing_unless_a_change_fails_or_is_committed(self) -> None:
        rewrite = "clang-format -i src/a.cpp"
        result = self._run({**CLANG_FORMAT, **github_job("ubuntu-latest", rewrite)})
        self.assertEqual(result, Result.failed(REWRITES.format("clang-format"), self.HINT))
        for files in (
            github_job("ubuntu-latest", rewrite, "git diff --exit-code"),
            github_job("ubuntu-latest", rewrite, "git commit -am 'Format' && git push"),
            _uses({"run": rewrite}, {"uses": "stefanzweifel/git-auto-commit-action@v5"}),
            # A pre-commit hook fails when it changes a file.
            {
                ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/pre-commit/mirrors-clang-format\n"
                "    rev: v18.1.8\n    hooks:\n      - id: clang-format\n",
                **github_job("ubuntu-latest", "pre-commit run --all-files"),
            },
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run({**CLANG_FORMAT, **files}).status, Status.PASS)

    def test_a_diff_a_later_step_fails_on_is_taken_to_enforce_heuristically(self) -> None:
        files = {
            **CLANG_FORMAT,
            **_uses(
                {"run": 'clang-format -i src/*.c\nDIFF=$(git diff)\necho "diff=$DIFF" >> $GITHUB_OUTPUT', "id": "f"},
                {"run": "exit 1", "if": "${{ steps.f.outputs.diff }}"},
            ),
        }
        self.assertEqual(self._run(files).status, Status.PASS)
        with temp_project(files) as root:
            [run] = [run for run in make_context(root).facts.of(ToolRun) if run.tool == "clang-format"]
        self.assertTrue(run.heuristic)

    def test_the_pre_commit_action_runs_the_hooks(self) -> None:
        hooks = "repos:\n  - repo: local\n    hooks:\n      - id: lint\n        name: Lint\n        entry: make lint\n"
        files = {
            **CLANG_FORMAT,
            ".pre-commit-config.yaml": hooks,
            "Makefile": "lint:\n\tclang-format -n -Werror src/a.c\n",
            **_uses({"uses": "pre-commit/action@v3.0.1"}),
        }
        self.assertEqual(self._run(files), Result.passed(".clang-format is defined and CI runs clang-format"))

    def test_printing_the_formatted_code_is_not_a_formatter_run(self) -> None:
        result = self._run({**CLANG_FORMAT, **github_job("ubuntu-latest", "clang-format --dry-run src/a.cpp")})
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_does_not_run_clang_format(self) -> None:
        result = self._run({**CLANG_FORMAT, **github_job("ubuntu-latest", "cmake -S . -B build")})
        self.assertEqual(result, Result.warned(".clang-format is defined but CI does not run clang-format", self.HINT))

    def test_mentioning_the_config_file_in_ci_does_not_count(self) -> None:
        workflow = {GITHUB_WORKFLOW: "on:\n  push:\n    paths-ignore: ['.clang-format', '_clang-format']\n"}
        self.assertEqual(self._run({**CLANG_FORMAT, **workflow}).status, Status.WARN)

    def test_running_clang_format_without_a_config_file_fails(self) -> None:
        result = self._run(github_job("ubuntu-latest", "clang-format --dry-run -Werror src/*.cpp"))
        self.assertEqual(
            result, Result.failed("no clang-format configuration found; formatting is not defined", self.HINT)
        )

    def test_python_and_rust_formatters_do_not_count(self) -> None:
        result = self._run(github_job("ubuntu-latest", "ruff format --check && cargo fmt --check"))
        self.assertEqual(result.status, Status.FAIL)

    def test_what_ci_configuration_that_is_not_parsed_hides_is_an_error_unless_allowed(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                result = self._run({**CLANG_FORMAT, **ci_running(provider, "cmake --build build")})
                self.assertEqual(result.status, Status.ERROR)
                self.assertEqual(
                    result.message,
                    "whether CI enforces the formatting is unknown: some of what it runs could not be read",
                )
                self.assertTrue(result.details[0].startswith("not read: the jobs and commands:"), result.details)
                allowed = self._run({**CLANG_FORMAT, **ci_running(provider, "cmake --build build")}, ALLOW_UNKNOWN)
                self.assertEqual(allowed.status, Status.WARN)
                # What is read counts, unknowns or not.
                checked = self._run({**CLANG_FORMAT, **ci_running(provider, "clang-format -n -Werror a.cpp")})
                self.assertEqual(checked.status, Status.PASS)


class PythonCodeFormattingTests(unittest.TestCase):
    HINT = "consider a CI job that runs ruff format --check (or black --check)"

    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, code_formatting, files, PYTHON)

    def test_formatter_in_any_ci_passes_with_its_default_style(self) -> None:
        commands = {"ruff format": "ruff format --check .", "black": "python -m black src tests --check"}
        # ruff format fails when it reformats a file with --exit-non-zero-on-format.
        self.assertEqual(self._run(github_job("x", "ruff format --exit-non-zero-on-format .")).status, Status.PASS)
        for provider in CI_FILES:
            for tool, command in commands.items():
                with self.subTest(ci=provider, tool=tool):
                    result = self._run(ci_running(provider, command))
                    self.assertEqual(result, Result.passed(f"CI enforces the {tool} style"))

    def test_formatter_actions_pass(self) -> None:
        for step, tool in (
            ({"uses": "psf/black@stable"}, "black"),
            ({"uses": "astral-sh/ruff-action@v3", "with": {"args": "format --check"}}, "ruff format"),
        ):
            with self.subTest(step=step):
                self.assertEqual(self._run(_uses(step)), Result.passed(f"CI enforces the {tool} style"))
        rewriting = self._run(_uses({"uses": "psf/black@stable", "with": {"options": "--verbose"}}))
        self.assertEqual(rewriting, Result.failed(REWRITES.format("black"), self.HINT))

    def test_configured_formatter_is_reported(self) -> None:
        configurations = {
            "pyproject.toml": "[project]\nname = 'app'\n\n[tool.ruff.format]\nquote-style = 'double'\n",
            "ruff.toml": "line-length = 120\n",
            ".ruff.toml": "line-length = 120\n",
        }
        for name, text in configurations.items():
            with self.subTest(name):
                result = self._run({name: text, **github_job("ubuntu-latest", "ruff format --diff")})
                self.assertEqual(result, Result.passed(f"{name} is defined and CI runs ruff format"))

    def test_another_formatters_configuration_does_not_define_the_style_ci_enforces(self) -> None:
        files = {
            "pyproject.toml": "[tool.black]\nline-length = 100\n",
            **github_job("ubuntu-latest", "ruff format --check"),
        }
        self.assertEqual(self._run(files), Result.passed("CI enforces the ruff format style"))

    def test_warns_when_configured_but_ci_does_not_format(self) -> None:
        files = {"pyproject.toml": "[tool.black]\nline-length = 100\n", **github_job("ubuntu-latest", "pytest")}
        expected = Result.warned("pyproject.toml is defined but CI does not run ruff format or black", self.HINT)
        self.assertEqual(self._run(files), expected)

    def test_fails_without_a_formatter(self) -> None:
        files = {"pyproject.toml": "[project]\nname = 'black'\n", **github_job("ubuntu-latest", "black-box-tests")}
        expected = Result.failed("CI never runs ruff format or black; its formatting is not enforced", self.HINT)
        self.assertEqual(self._run(files), expected)

    def test_black_that_only_rewrites_files_does_not_count(self) -> None:
        result = self._run(github_job("ubuntu-latest", "black ."))
        self.assertEqual(result, Result.failed(REWRITES.format("black"), self.HINT))

    def test_the_ruff_format_hook_enforces_when_ci_runs_pre_commit(self) -> None:
        hooks = (
            "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.12.0\n"
            "    hooks:\n      - id: ruff-format\n"
        )
        files = {".pre-commit-config.yaml": hooks, **github_job("ubuntu-latest", "uvx pre-commit run -a")}
        self.assertEqual(self._run(files), Result.passed("CI enforces the ruff format style"))
        # Hooks that CI never runs enforce nothing.
        self.assertEqual(self._run({".pre-commit-config.yaml": hooks}).status, Status.FAIL)

    def test_clang_format_does_not_count_but_python_formatting_does(self) -> None:
        statuses = {"C++": self._run(WELL_CONFIGURED).status, "Python": self._run(dict(WELL_CONFIGURED_PYTHON)).status}
        self.assertEqual(statuses, {"C++": Status.FAIL, "Python": Status.PASS})


class RustCodeFormattingTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, code_formatting, files, RUST)

    def test_rustfmt_in_any_ci_passes_with_its_default_style(self) -> None:
        commands = ("cargo fmt --all -- --check", "cargo +nightly fmt --check", "rustfmt --check src/lib.rs")
        for provider in CI_FILES:
            for command in commands:
                with self.subTest(ci=provider, command=command):
                    result = self._run(ci_running(provider, command))
                    self.assertEqual(result, Result.passed("CI enforces the rustfmt style"))

    def test_the_rustfmt_action_passes(self) -> None:
        result = self._run(_uses({"uses": "actions-rust-lang/rustfmt@v1"}))
        self.assertEqual(result, Result.passed("CI enforces the rustfmt style"))

    def test_configured_rustfmt_is_reported(self) -> None:
        for name in ("rustfmt.toml", ".rustfmt.toml"):
            with self.subTest(name):
                result = self._run({name: "max_width = 120\n", **github_job("ubuntu-latest", "cargo fmt --check")})
                self.assertEqual(result, Result.passed(f"{name} is defined and CI runs rustfmt"))

    def test_warns_when_ci_only_mentions_the_config_file(self) -> None:
        result = self._run({"rustfmt.toml": "edition = '2024'\n", GITHUB_WORKFLOW: "paths: ['rustfmt.toml']\n"})
        expected = Result.warned(
            "rustfmt.toml is defined but CI does not run rustfmt", "consider a CI job that runs cargo fmt --check"
        )
        self.assertEqual(result, expected)

    def test_fails_without_rustfmt(self) -> None:
        self.assertEqual(self._run(github_job("ubuntu-latest", "cargo test")).status, Status.FAIL)

    def test_well_configured_rust_project_passes(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_RUST)).status, Status.PASS)


class UnitCodeFormattingTests(unittest.TestCase):
    WORKSPACE: ClassVar[dict[str, str]] = {
        "Cargo.toml": '[workspace]\nmembers = ["a", "b"]\n',
        "a/Cargo.toml": '[package]\nname = "a"\n',
        "a/src/lib.rs": "",
        "b/Cargo.toml": '[package]\nname = "b"\n',
        "b/src/lib.rs": "",
    }

    def _run(self, files: dict[str, str]) -> Result:
        """The result for exactly `files`: the layouts would add sources to the workspace root."""
        with temp_project(files) as root:
            return code_formatting.run(make_context(root))

    def test_each_unit_of_a_workspace_is_judged_where_ci_runs_its_formatter(self) -> None:
        result = self._run({**self.WORKSPACE, **github_job("ubuntu-latest", "cd a && cargo fmt --check")})
        self.assertEqual(
            result,
            Result.failed(
                "a: CI enforces the rustfmt style; b: CI never runs rustfmt; its formatting is not enforced",
                "b: consider a CI job that runs cargo fmt --check",
            ),
        )

    def test_a_run_from_the_root_formats_every_unit(self) -> None:
        result = self._run({**self.WORKSPACE, **github_job("ubuntu-latest", "cargo fmt --all --check")})
        self.assertEqual(result, Result.passed("CI enforces the rustfmt style"))

    def test_a_style_file_applies_to_the_units_below_it(self) -> None:
        files = {**self.WORKSPACE, "b/rustfmt.toml": "max_width = 100\n", **github_job("ubuntu-latest", "cargo test")}
        result = self._run(files)
        self.assertIn("b: b/rustfmt.toml is defined but CI does not run rustfmt", result.message)
        self.assertIn("a: CI never runs rustfmt", result.message)


class MixedLanguageCodeFormattingTests(unittest.TestCase):
    def test_every_language_needs_a_formatter_and_findings_are_labelled(self) -> None:
        result = run_as(self, code_formatting, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(
            result,
            Result.failed(
                "C/C++: .clang-format is defined and CI runs clang-format; "
                "Python: CI never runs ruff format or black; its formatting is not enforced",
                "Python: consider a CI job that runs ruff format --check (or black --check)",
            ),
        )

    def test_passes_when_every_language_is_formatted(self) -> None:
        workflow = WELL_CONFIGURED[GITHUB_WORKFLOW] + "      - run: ruff format --check\n"
        result = run_as(self, code_formatting, {**WELL_CONFIGURED, GITHUB_WORKFLOW: workflow}, C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.PASS)


class AnswerTests(unittest.TestCase):
    def test_a_language_no_known_tool_formats_is_skipped(self) -> None:
        answer = tool_answer(FORMAT, Enforcement.CHECK, "Lang", Facts(()), ())
        self.assertEqual(answer.answer, Answer.IMPOSSIBLE)
        self.assertEqual(judge_formatting(answer), Result(status=Status.SKIP, message="no known tool formats Lang"))

    def test_a_language_only_auxiliary_code_uses_is_judged_as_advisory(self) -> None:
        files = {"CMakeLists.txt": "project(app)\n", "src/a.cpp": "", "docs/conf.py": "", **CLANG_FORMAT}
        files |= github_job("ubuntu-latest", "clang-format -n -Werror src/a.cpp")
        with temp_project(files) as root:
            self.assertEqual(code_formatting.run(make_context(root)).status, Status.FAIL)
            context = make_context(root, auxiliary=("docs",))
            self.assertIn("Python", context.structure.languages)
            result = code_formatting.run(context)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn(
            "C/C++: .clang-format is defined and CI runs clang-format; Python (auxiliary: docs): CI never runs ",
            result.message,
        )
        self.assertIn(
            "Python (auxiliary: docs): a warning, not a failure: the Python here is auxiliary code (--auxiliary docs)",
            result.details,
        )
