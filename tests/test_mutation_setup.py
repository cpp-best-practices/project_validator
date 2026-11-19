"""The repository's own mutation testing: mutmut runs the suite in a copy of the tree, so the copy must hold every
top-level package the tests import, and the workflow must fail when mutmut does."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "mutation-testing.yml"


def _imported_top_level_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("*.py"):
        if "fixtures" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


class MutationSetupTests(unittest.TestCase):
    def test_every_repository_package_the_tests_import_is_copied_for_mutmut(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]
        copied = {Path(path).parts[0] for path in (*config["source_paths"], *config["also_copy"])}
        copied.add("tests")  # mutmut copies the tests directory itself
        packages = {name for name in _imported_top_level_names() if (ROOT / name / "__init__.py").is_file()}
        self.assertEqual(packages - copied, set())

    def test_steps_that_pipe_mutmut_fail_when_mutmut_fails(self) -> None:
        # GitHub runs a step without an explicit shell as "bash -e {0}", where a pipeline's status is its last
        # command's: "mutmut run | tee run.log" would read as success whatever mutmut returned. An explicit
        # "shell: bash" runs it as "bash --noprofile --norc -eo pipefail {0}".
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        default = workflow.get("defaults", {}).get("run", {}).get("shell")
        for job in workflow["jobs"].values():
            job_default = job.get("defaults", {}).get("run", {}).get("shell", default)
            for step in job["steps"]:
                script = step.get("run", "")
                if any("mutmut" in line and "|" in line for line in script.splitlines()):
                    self.assertEqual(step.get("shell", job_default), "bash", step.get("name"))

    def test_the_mutation_step_caps_each_worker_s_memory(self) -> None:
        # A mutant that breaks a loop's progress while it appends grows without bound, faster than mutmut's CPU-time
        # limit stops it; a cap makes it fail as a kill instead of exhausting the runner.
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        scripts = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
        running = [script for script in scripts if "mutmut run" in script]
        self.assertTrue(running)
        for script in running:
            self.assertRegex(script, r"\bulimit -[vd] \d+")

    @unittest.skipIf(
        sys.platform == "win32",
        "the mutation workflow runs on Linux; the bash Windows finds first is the WSL launcher, with no Linux",
    )
    def test_running_out_of_budget_is_reported_not_failed(self) -> None:
        # timeout sends INT at the budget's end and KILL two minutes later: mutmut busy in its stats pass ignores the
        # INT, so a pull request with too much to mutate ends in 137, which is the budget running out, as 124 is.
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        script = next(
            step["run"] for step in workflow["jobs"]["mutmut"]["steps"] if "budget_minutes" in step.get("run", "")
        )
        check = next(line.strip() for line in script.splitlines() if line.strip().startswith('[ "$status" -eq 0 ]'))
        for status, code in (("0", 0), ("124", 0), ("137", 0), ("1", 1)):
            with self.subTest(status=status):
                ran = subprocess.run(  # noqa: S603 - bash with the workflow's own line
                    ["bash", "-c", f"status={status}; {check}"],  # noqa: S607 - bash from PATH
                    check=False,
                )
                self.assertEqual(min(ran.returncode, 1), code)

    def test_the_budget_and_its_kill_fit_in_the_job_s_timeout(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["mutmut"]
        script = next(step["run"] for step in job["steps"] if "budget_minutes" in step.get("run", ""))
        budget = int(re.search(r"budget_minutes=(\d+)", script)[1])  # type: ignore[index]
        # The priming run's 5 minutes, the budget, timeout's 2 minutes before KILL, and setup and the report.
        self.assertLessEqual(5 + budget + 2 + 5, job["timeout-minutes"])
        self.assertGreaterEqual(budget, 30)

    def test_the_fresh_import_test_is_left_out_of_mutation_runs(self) -> None:
        # It imports every module afresh, so mutmut maps every import-time function to it, yet it only fails on a
        # mutant that breaks an import: each such mutant paid its 70 seconds and survived.
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]
        arguments = config["pytest_add_cli_args"]
        test = "tests/test_architecture.py::ArchitectureTests::test_every_module_imports_on_its_own"
        self.assertIn(test, [arguments[index + 1] for index, word in enumerate(arguments[:-1]) if word == "--deselect"])


if __name__ == "__main__":
    unittest.main()
