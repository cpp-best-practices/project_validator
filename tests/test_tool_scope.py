"""Which of the project's code a tool's run covers."""

from __future__ import annotations

import unittest

from project_validator.facts.tools import ToolRun
from tests.support import github_job, make_context, temp_project

PROJECT = {"pyproject.toml": "[project]\nname = 'app'\n", "src/app.py": "", "tests/test_app.py": ""}


class ToolScopeTests(unittest.TestCase):
    def _scopes(self, command: str) -> set[tuple[str, ...]]:
        with temp_project({**PROJECT, **github_job("ubuntu-latest", command)}) as root:
            runs = make_context(root).facts.of(ToolRun)
            # ruff format serves notebooks too; its run for them is another run.
            return {run.scope for run in runs if run.tool == "ruff format" and "Python" in run.languages}

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


class ToolsAskedTests(unittest.TestCase):
    def test_only_the_tools_of_the_projects_languages_and_formats_record_runs(self) -> None:
        """A shared tool serves many languages; its run is recorded for the project's, not for every one it serves."""
        ci = github_job("ubuntu-latest", "cargo test", "ruff format --check src", "kcov coverage bats tests")
        with temp_project({**PROJECT, **ci}) as root:
            runs = make_context(root).facts.of(ToolRun)
        self.assertEqual({run.tool for run in runs}, {"ruff format"})
        self.assertTrue(all("Python" in run.languages for run in runs))
