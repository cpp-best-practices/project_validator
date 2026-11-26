"""super-linter, configured by its `VALIDATE_<LINTER>` switches in the environment: the linters it runs are those the
switches leave on (upstream #224)."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.copy_paste_detection import copy_paste_detection
from project_validator.checks.secret_scanning import secret_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Status
from project_validator.facts import Command, Facts, Origin
from project_validator.facts.tools import known_tools
from project_validator.tools.super_linter import LINTERS
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

_ORIGIN = Origin(path=GITHUB_WORKFLOW)
_NO_FACTS = Facts()
# The linters a check reads from the commands themselves, rather than a tool's claim.
_READ_BY_CHECKS = frozenset({"GITLEAKS", "JSCPD"})
SCRIPTS = {"scripts/deploy.sh": "#!/bin/sh\necho deploy\n", "tools/check.py": "print('ok')\n"}


def _workflow(uses: str, step_env: Mapping[str, str] | None = None, **levels: Mapping[str, str]) -> dict[str, str]:
    """A workflow whose one job uses super-linter, with `step_env` on the step and `levels` (`workflow`, `job`)."""
    step: dict[str, object] = {"uses": uses}
    if step_env:
        step["env"] = dict(step_env)
    job: dict[str, object] = {"runs-on": "ubuntu-latest", "steps": [{"uses": "actions/checkout@v5"}, step]}
    if "job" in levels:
        job["env"] = dict(levels["job"])
    workflow: dict[str, object] = {"jobs": {"lint": job}}
    if "workflow" in levels:
        workflow["env"] = dict(levels["workflow"])
    return {GITHUB_WORKFLOW: json.dumps(workflow)}


def _commands(files: Mapping[str, str]) -> list[Command]:
    with temp_project({**SCRIPTS, **files}) as root:
        facts = make_context(root).facts
    return [
        command for command in facts.of(Command) if command.line.startswith("uses: ") and "super-linter" in command.line
    ]


def _programs(files: Mapping[str, str]) -> set[str]:
    return {command.argv[0] for command in _commands(files)}


class SuperLinterTests(unittest.TestCase):
    def test_every_linter_runs_unless_a_switch_says_otherwise(self) -> None:
        """grafana/helm-charts: `docker://github/super-linter:v3.12.0` with only YAML and kubeval switched off still
        runs shellcheck over its scripts."""
        files = _workflow(
            "docker://github/super-linter:v3.12.0",
            {"VALIDATE_ALL_CODEBASE": "false", "VALIDATE_KUBERNETES_KUBEVAL": "false", "VALIDATE_YAML": "false"},
        )
        programs = _programs(files)
        self.assertTrue({"shellcheck", "flake8"} <= programs, programs)
        self.assertNotIn("yamllint", programs)
        with temp_project({**SCRIPTS, **files}) as root:
            result = static_analysis.run(make_context(root))
        self.assertIn("Shell: shellcheck runs", result.message)

    def test_version_3_runs_only_the_linters_it_had(self) -> None:
        """super-linter 3 (grafana/helm-charts' v3.12.0) had shellcheck and flake8, but not gitleaks, jscpd, actionlint,
        checkov or kubeconform, which later versions added."""
        for uses in ("docker://github/super-linter:v3.12.0", "github/super-linter@v3", "github/super-linter@v3.17.1"):
            with self.subTest(uses=uses):
                programs = _programs(_workflow(uses))
                self.assertTrue({"shellcheck", "flake8"} <= programs, programs)
                self.assertFalse({"gitleaks", "jscpd", "actionlint", "checkov", "kubeconform"} & programs, programs)
        self.assertIn("gitleaks", _programs(_workflow("super-linter/super-linter@v7")))
        self.assertIn("gitleaks", _programs(_workflow("super-linter/super-linter@" + "a" * 40)))

    def test_validating_the_whole_codebase_is_no_linter_switch(self) -> None:
        """`VALIDATE_ALL_CODEBASE` says which files are linted (all, or those changed), not which linters run."""
        for value in ("true", "false"):
            with self.subTest(value=value):
                programs = _programs(_workflow("super-linter/super-linter@v7", {"VALIDATE_ALL_CODEBASE": value}))
                self.assertIn("shellcheck", programs)

    def test_a_switch_set_true_runs_only_the_linters_switched_on(self) -> None:
        files = _workflow("super-linter/super-linter@v7", {"VALIDATE_PYTHON_FLAKE8": "true", "VALIDATE_BASH": "TRUE"})
        self.assertEqual(_programs(files), {"flake8", "shellcheck"})

    def test_the_switches_count_from_the_job_and_the_workflow_too(self) -> None:
        for level in ("job", "workflow"):
            with self.subTest(level=level):
                env = {"VALIDATE_PYTHON_FLAKE8": "true"}
                self.assertEqual(_programs(_workflow("super-linter/super-linter/slim@v7", **{level: env})), {"flake8"})

    def test_each_name_of_the_action_is_known(self) -> None:
        for uses in (
            "super-linter/super-linter@v7.2.0",
            "super-linter/super-linter/slim@v7",
            "github/super-linter@v4",
            "github/super-linter/slim@v4",
            "docker://ghcr.io/super-linter/super-linter:slim-v7",
            "docker://github/super-linter:v3",
        ):
            with self.subTest(uses=uses):
                self.assertIn("shellcheck", _programs(_workflow(uses)))

    def test_with_errors_disabled_it_only_reports(self) -> None:
        commands = _commands(_workflow("super-linter/super-linter@v7", {"DISABLE_ERRORS": "true"}))
        self.assertTrue(commands)
        self.assertTrue(all(command.advisory for command in commands), commands)
        self.assertFalse(any(command.advisory for command in _commands(_workflow("super-linter/super-linter@v7"))))

    def test_gitleaks_and_jscpd_count_for_their_checks(self) -> None:
        files = {**SCRIPTS, **_workflow("super-linter/super-linter@v7")}
        with temp_project(files) as root:
            context = make_context(root)
            self.assertEqual(secret_scanning.run(context).status, Status.PASS)
            self.assertEqual(copy_paste_detection.run(context).status, Status.PASS)

    def test_shellcheck_is_the_shell_lint(self) -> None:
        files = {**SCRIPTS, **_workflow("github/super-linter@v4")}
        with temp_project(files) as root:
            result = compiler_warnings.run(make_context(root))
        self.assertNotIn("enable at least shellcheck", result.message)

    def test_every_linter_is_a_tool_the_validator_knows(self) -> None:
        """Each command super-linter runs is claimed by a known tool: a linter no tool claims would count for
        nothing."""
        tools = known_tools()
        for switch, argv in LINTERS.items():
            if switch in _READ_BY_CHECKS:
                continue
            with self.subTest(switch=switch):
                command = Command(origin=_ORIGIN, job="lint", argv=argv, line=" ".join(argv))
                runs = (tool.claims(command, _NO_FACTS) for tool in tools)
                self.assertTrue(any(run is not None and any(run.provides.values()) for run in runs), argv)


if __name__ == "__main__":
    unittest.main()
