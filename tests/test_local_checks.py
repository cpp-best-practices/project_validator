"""Without CI, a local check script or task is read as the pipeline (upstream #384): the project is judged at an entry
level, its CI-only checks warning rather than failing."""

from __future__ import annotations

import unittest

from project_validator.ci.local_checks import LOCAL_CHECKS, entry_command, local_check_files
from project_validator.core import Options, Status
from project_validator.plugins import discover
from project_validator.runner import run_check
from tests.support import make_context, temp_project
from tests.test_cli import run_cli

MAKEFILE = "check:\n\truff check .\n\tpytest\n"
PYTHON = {"pkg/__init__.py": "", "tests/test_pkg.py": "def test_x():\n    pass\n", "Makefile": MAKEFILE}
WORKFLOW = "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"


def _check(name: str):  # type: ignore[no-untyped-def]
    return next(found for found in discover().checks if found.name == name)


class EntryPointTests(unittest.TestCase):
    def test_each_kind_of_entry_point_is_found_with_how_it_runs(self) -> None:
        cases = {
            "check.sh": ("#!/bin/sh\npytest\n", "sh check.sh"),
            "scripts/check.sh": ("pytest\n", "sh scripts/check.sh"),
            "scripts/check.ps1": ("pytest\n", "pwsh -File scripts/check.ps1"),
            "check.py": ("import subprocess\n", "python check.py"),
            "Makefile": (MAKEFILE, "make check"),
            "justfile": ("check:\n    pytest\n", "just check"),
            "package.json": ('{"scripts": {"check": "eslint ."}}', "npm run check"),
            "composer.json": ('{"scripts": {"check": "phpunit"}}', "composer check"),
            ".pre-commit-config.yaml": ("repos: []\n", "pre-commit run --all-files"),
        }
        for path, (text, command) in cases.items():
            with self.subTest(path=path), temp_project({path: text}) as root:
                context = make_context(root)
                self.assertEqual([found.path for found in local_check_files(context.project)], [path])
                self.assertEqual(entry_command(path), command)

    def test_a_makefile_or_package_without_a_check_target_is_no_entry_point(self) -> None:
        files = {
            "Makefile": "all:\n\tcc main.c\ncheck := yes\n",  # a variable named check, no target
            "package.json": '{"scripts": {"test": "jest"}}',
            "composer.json": "[]",  # not a manifest of scripts at all
        }
        with temp_project(files) as root:
            self.assertEqual(local_check_files(make_context(root).project), ())

    def test_real_ci_is_the_pipeline_when_there_is_some(self) -> None:
        with temp_project({**PYTHON, ".github/workflows/ci.yml": WORKFLOW}) as root:
            providers = {found.provider.name for found in make_context(root).ci_files}
        self.assertEqual(providers, {"GitHub Actions"})

    def test_without_ci_the_local_checks_are_the_pipeline(self) -> None:
        with temp_project(PYTHON) as root:
            context = make_context(root)
            self.assertEqual([(found.provider, found.path) for found in context.ci_files], [(LOCAL_CHECKS, "Makefile")])
            self.assertTrue(context.local_pipeline)
            tests = run_check(_check("tests-run"), context)
        self.assertNotIn("no CI", tests.message)
        self.assertIn("pytest", " ".join((tests.message, *tests.details)))


class EntryLevelTests(unittest.TestCase):
    def test_ci_present_warns_naming_the_local_checks(self) -> None:
        with temp_project(PYTHON) as root:
            result = run_check(_check("ci-present"), make_context(root))
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("make check", result.message)
        self.assertIn("entry level", result.message)

    def test_a_ci_only_check_that_would_fail_warns_instead(self) -> None:
        with temp_project(PYTHON) as root:
            result = run_check(_check("platform-matrix"), make_context(root))
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("entry level", " ".join(result.details))
        self.assertTrue(all(place.result.status is not Status.FAIL for place in result.places))

    def test_a_ci_only_check_that_does_not_fail_is_left_as_it_is(self) -> None:
        with temp_project(PYTHON) as root:
            result = run_check(_check("action-pinning"), make_context(root))
        self.assertEqual(result.status, Status.SKIP)  # no actions to pin

    def test_a_check_of_the_code_still_fails(self) -> None:
        with temp_project(PYTHON) as root:
            result = run_check(_check("type-checking"), make_context(root))
        self.assertIn(result.status, (Status.FAIL, Status.WARN))
        self.assertNotIn("entry level", " ".join(result.details))

    def test_without_ci_or_local_checks_ci_present_fails(self) -> None:
        with temp_project({"pkg/__init__.py": ""}) as root:
            context = make_context(root)
            self.assertFalse(context.local_pipeline)
            self.assertEqual(run_check(_check("ci-present"), context).status, Status.FAIL)


class FlagTests(unittest.TestCase):
    def test_the_flag_names_the_script(self) -> None:
        with temp_project({"pkg/__init__.py": "", "tools/all.sh": "pytest\n"}) as root:
            context = make_context(root, Options(local_checks="tools/all.sh"))
            self.assertEqual([found.path for found in context.ci_files], ["tools/all.sh"])

    def test_the_flag_s_script_must_exist(self) -> None:
        with temp_project({"pkg/__init__.py": ""}) as root:
            code, _, errors = run_cli("--local-checks", "missing.sh", str(root))
        self.assertEqual(code, 2)
        self.assertIn("missing.sh", errors)
