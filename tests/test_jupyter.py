"""The Jupyter profile: notebooks as a format, parsed, run as tests, formatted and linted."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.jupyter import JUPYTER_ECOSYSTEM, NOTEBOOK_PARSER
from project_validator.facts.wellformed import ParseError
from tests.layouts.jupyter import PRICES, notebook
from tests.support import github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Jupyter notebooks"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _problem(text: str) -> str:
    try:
        NOTEBOOK_PARSER.parse("n.ipynb", text.encode())
    except ParseError as error:
        return error.message
    return ""


class RecognitionAndParsingTests(unittest.TestCase):
    def test_notebooks_are_the_format_and_parse_as_notebooks(self) -> None:
        with temp_project({"notebooks/prices.ipynb": PRICES, "analysis.py": "x = 1\n"}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.formats), (frozenset({"Python"}), frozenset({"Jupyter"})))
        self.assertEqual(structure.recognised_by["Jupyter"], (".ipynb files",))
        self.assertEqual((JUPYTER_ECOSYSTEM.kind, JUPYTER_ECOSYSTEM.toolchain), ("format", None))
        self.assertEqual(_problem(notebook("x = 1\n")), "")
        self.assertEqual(_problem('{"nbformat": 4}'), "not a notebook: no cells")
        self.assertEqual(_problem('{"cells": []}'), "not a notebook: no nbformat version")
        self.assertEqual(_problem("[]"), "not a notebook: the document is not an object")
        self.assertEqual(_problem('{"cells": [}'), "Expecting value")

    def test_ci_usage(self) -> None:
        for text in ("jupyter nbconvert --execute n.ipynb", "papermill in.ipynb out.ipynb", "nbqa ruff notebooks"):
            with self.subTest(text=text):
                self.assertTrue(uses(JUPYTER_ECOSYSTEM, text))
        self.assertFalse(uses(JUPYTER_ECOSYSTEM, "pytest"))


class JupyterTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_notebooks_run_as_tests(self) -> None:
        for line in (
            "pytest --nbmake notebooks",
            "pytest --nbval-lax notebooks",
            "jupyter nbconvert --to notebook --execute notebooks/prices.ipynb",
            "jupyter execute notebooks/prices.ipynb",
            "papermill notebooks/prices.ipynb /tmp/out.ipynb",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, _ci(line)), Result.passed("tests found in 1 file(s)"))
        # pytest without the plugin, or a conversion without executing, runs no notebook.
        for line in ("pytest tests", "jupyter nbconvert --to html notebooks/prices.ipynb"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, _ci(line)).status, Status.WARN)

    def test_ruff_and_nbqa_format_and_lint_the_notebooks(self) -> None:
        for line in ("ruff format --check notebooks", "nbqa black --check notebooks", "nbqa ruff format --check ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.PASS)
        for line in ("ruff format notebooks", "nbqa black notebooks"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)
        for line in ("ruff check notebooks", "nbqa ruff notebooks", "nbqa flake8 notebooks", "nbqa pylint notebooks"):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)), Result.passed("ruff check runs"))
        configured = {"ruff.toml": "line-length = 100\n", **_ci("ruff check notebooks")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("ruff check (ruff.toml) runs"))
        for line in ("nbqa ruff format --check .", "nbqa isort notebooks", "ruff format --check notebooks"):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)).status, Status.FAIL)

    def test_the_checkpoints_are_ignored_and_never_committed(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": ".ipynb_checkpoints/\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "**/.ipynb_checkpoints\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.log\n"}).status, Status.WARN)
        # A checkpoint committed is a build output committed: the bare fixture, whose files git tracks, shows it.
        self.assertEqual(self._run(data_wellformed, {}), Result.passed("1 Jupyter file parses"))
