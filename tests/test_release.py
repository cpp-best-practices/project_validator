"""Releasing the validator (upstream #337): one name everywhere (`project_validator`: the repository, the import, the
PyPI package and the command), one version, `--version`, and the metadata a published package needs."""

from __future__ import annotations

import contextlib
import io
import tomllib
import unittest
from pathlib import Path

import project_validator
from project_validator.cli import EXIT_SUCCESS, deprecated_main, main

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class NameTests(unittest.TestCase):
    def test_the_package_and_its_command_share_the_repositorys_name(self) -> None:
        project = PYPROJECT["project"]
        self.assertEqual(project["name"], "project_validator")
        self.assertEqual(project["scripts"]["project_validator"], "project_validator.cli:main")

    def test_the_old_command_still_runs_and_says_it_is_deprecated(self) -> None:
        self.assertEqual(PYPROJECT["project"]["scripts"]["project-validator"], "project_validator.cli:deprecated_main")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = deprecated_main(["--list"])
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("platform-matrix", stdout.getvalue())
        self.assertIn("`project-validator` is deprecated: run `project_validator`", stderr.getvalue())


class VersionTests(unittest.TestCase):
    def test_the_version_has_one_source(self) -> None:
        self.assertEqual(PYPROJECT["project"]["dynamic"], ["version"])
        self.assertNotIn("version", PYPROJECT["project"])
        attribute = PYPROJECT["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        self.assertEqual(attribute, "project_validator.__version__")

    def test_version_prints_the_packages_version(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue(), f"project_validator {project_validator.__version__}\n")


class MetadataTests(unittest.TestCase):
    def test_the_package_says_what_it_is_and_where_it_lives(self) -> None:
        project = PYPROJECT["project"]
        self.assertEqual(project["license"], "Unlicense")
        self.assertIn("Programming Language :: Python :: 3.12", project["classifiers"])
        self.assertIn("Development Status :: 3 - Alpha", project["classifiers"])
        urls = project["urls"]
        self.assertEqual(urls["Repository"], "https://github.com/cpp-best-practices/project_validator")
        self.assertEqual(urls["Issues"], "https://github.com/cpp-best-practices/project_validator/issues")
