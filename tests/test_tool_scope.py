"""Which of the project's code a tool's run covers."""

import unittest

from project_validator.facts.tools import ToolRun
from tests.support import github_job, make_context, temp_project

PROJECT = {"pyproject.toml": "[project]\nname = 'app'\n", "src/app.py": "", "tests/test_app.py": ""}


class ToolScopeTests(unittest.TestCase):
    def _scopes(self, command: str) -> set[tuple[str, ...]]:
        with temp_project({**PROJECT, **github_job("ubuntu-latest", command)}) as root:
            return {run.scope for run in make_context(root).facts.of(ToolRun) if run.tool == "ruff format"}

    def test_a_run_on_files_ci_wrote_covers_none_of_the_project(self) -> None:
        self.assertEqual(self._scopes("echo 'x = 1' > scratch.py && ruff format --check scratch.py"), {()})

    def test_a_run_on_the_projects_files_or_directories_covers_them(self) -> None:
        commands = (
            "ruff format --check scratch.py",
            "touch scratch.py && ruff format --check src/app.py scratch.py",
            "ruff format --check src",
            "ruff format --check",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self._scopes(command), {(".",)})
