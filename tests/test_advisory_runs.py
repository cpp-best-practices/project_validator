"""Advisory runs: a tool run in a step or job that cannot fail the pipeline (`continue-on-error`, `allow_failure`)
runs, but enforces nothing, so it satisfies no check; the finding says it runs, and why it cannot fail."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from project_validator.facts.tools import ToolRun
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

PYTHON = {
    "pyproject.toml": "[project]\nname = 'app'\n\n[tool.ruff]\nline-length = 100\n",
    "src/app.py": "",
}


def _workflow(*steps: dict[str, object], **job: object) -> dict[str, str]:
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"check": {"runs-on": "ubuntu-latest", "steps": steps, **job}}})}


def _result(check: Check, files: dict[str, str]) -> Result:
    with temp_project(files) as root:
        return check.run(make_context(root))


class AdvisoryRunTests(unittest.TestCase):
    def test_a_run_in_an_advisory_step_says_why_it_cannot_fail(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff check .", "continue-on-error": True}, {"run": "ruff format ."})}
        with temp_project(files) as root:
            runs = make_context(root).facts.of(ToolRun)
        self.assertEqual(
            {(run.tool, run.advisory) for run in runs}, {("ruff check", "continue-on-error"), ("ruff format", "")}
        )

    def test_an_advisory_run_is_no_gate_and_the_finding_says_it_runs(self) -> None:
        files = {**PYTHON, **_workflow({"run": "ruff format --check .", "continue-on-error": True})}
        result = _result(code_formatting, files)
        self.assertNotEqual(result.status, Status.PASS, result)
        self.assertIn("ruff format runs in CI but cannot fail it (continue-on-error)", result.details, result)

    def test_a_gating_run_beside_an_advisory_one_passes(self) -> None:
        steps = ({"run": "ruff check .", "continue-on-error": True}, {"run": "ruff check src"})
        result = _result(static_analysis, {**PYTHON, **_workflow(*steps)})
        self.assertEqual(result.status, Status.PASS, result)
        self.assertFalse([detail for detail in result.details if "cannot fail" in detail], result)

    def test_an_allow_failure_job_runs_its_tools_advisedly(self) -> None:
        pipeline = {"style": {"script": ["ruff format --check ."], "allow_failure": True}}
        result = _result(code_formatting, {**PYTHON, ".gitlab-ci.yml": json.dumps(pipeline)})
        self.assertNotEqual(result.status, Status.PASS, result)
        self.assertIn("ruff format runs in CI but cannot fail it (allow_failure)", result.details, result)
