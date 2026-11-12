"""The Racket profile's rules, judged by the generic checks in the Racket package and Racket sources layouts."""

from __future__ import annotations

import unittest
from pathlib import Path

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.coverage import coverage
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.racket import RACKET_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, run_as, temp_project, uses

RACKET = frozenset({"Racket"})
TESTS = {"shop.rkt": "#lang racket/base\n(module+ test\n  (require rackunit)\n  (check-equal? 1 1))\n"}
RACKET_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            racket-version: ["8.12", "stable"]
            variant: [CS, BC]
        steps:
          - uses: Bogdanp/setup-racket@v1.16
            with:
              version: ${{ matrix.racket-version }}
              variant: ${{ matrix.variant }}
          - run: raco test .
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_sources_and_the_package_file(self) -> None:
        files = {"info.rkt": "#lang info\n", "main.rkt": "", "scribblings/shop.scrbl": "", "data/prices.rktd": ""}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (RACKET, frozenset({"raco pkg"})))
        self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"src/shop.rkt": ""}) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset())

    def test_compiled_directories_are_build_trees(self) -> None:
        with temp_project({"main.rkt": "", "compiled/main_rkt.zo": "", "src/compiled/x.zo": ""}) as root:
            self.assertTrue(is_build_tree(Path(root, "compiled")))
            self.assertTrue(is_build_tree(Path(root, "src", "compiled")))
            self.assertFalse(is_build_tree(Path(root, "src")))

    def test_ci_usage(self) -> None:
        for text in ("raco test .", "raco pkg install --auto", "uses: Bogdanp/setup-racket@v1.16", "racket main.rkt"):
            with self.subTest(text=text):
                self.assertTrue(uses(RACKET_ECOSYSTEM, text))
        self.assertFalse(uses(RACKET_ECOSYSTEM, "npm test"))


class RacketTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, RACKET_ECOSYSTEM)

    def test_raco_test_runs_the_rackunit_tests(self) -> None:
        for line in ("raco test .", "raco test -x -p shop", "raco cover ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        required = {"tests/shop-test.rkt": '#lang racket/base\n(require rackunit "../shop.rkt")\n(check-true #t)\n'}
        self.assertEqual(self._run(tests_run, {**required, **_ci("raco test tests")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TESTS, **_ci("raco make main.rkt")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("raco test .")).status, Status.FAIL)

    def test_raco_cover_measures_expressions(self) -> None:
        for line in ("raco cover .", "raco cover -f codecov -d coverage ."):
            with self.subTest(line=line):
                result = self._run(coverage, _ci(line))
                self.assertEqual(result, Result.passed("statement coverage is reported with raco cover"))
        self.assertEqual(self._run(coverage, _ci("raco test .")).status, Status.FAIL)

    def test_raco_fmt_rewrites_and_the_diff_enforces(self) -> None:
        enforced = _ci("raco fmt -i $(git ls-files '*.rkt')", "git diff --exit-code")
        self.assertEqual(self._run(code_formatting, enforced), Result.passed("CI enforces the raco fmt style"))
        self.assertEqual(self._run(code_formatting, _ci("raco fmt -i main.rkt")).status, Status.FAIL)
        # Without -i, raco fmt only prints.
        self.assertEqual(self._run(code_formatting, _ci("raco fmt main.rkt")).status, Status.FAIL)

    def test_compiled_directories_must_be_ignored(self) -> None:
        for ignored in ("compiled/\n", "**/compiled/\n", "compiled\n"):
            with self.subTest(ignored=ignored):
                self.assertEqual(self._run(vcs_ignore, {".gitignore": ignored}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.zo\n"}).status, Status.WARN)

    def test_the_platform_matrix_pairs_versions_with_variants(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: RACKET_MATRIX})
        self.assertIn("4 Racket version(s) (8.12 BC, 8.12 CS, stable BC, stable CS)", result.message)
        for files, version in (
            (_ci("docker run racket/racket:8.14-full raco test ."), "8.14"),
            (_ci("raco test ."), "default"),
        ):
            with self.subTest(files=files):
                self.assertIn(f"1 Racket version(s) ({version})", self._run(platform_matrix, files).message)
        # Another action's `version` input names no Racket version.
        other = github_steps("uses: fortran-lang/setup-fortran@v1", "run: raco test .")
        other[GITHUB_WORKFLOW] = other[GITHUB_WORKFLOW].replace(
            '"uses": "fortran-lang/setup-fortran@v1"',
            '"uses": "fortran-lang/setup-fortran@v1", "with": {"version": "14"}',
        )
        self.assertIn("1 Racket version(s) (default)", self._run(platform_matrix, other).message)
