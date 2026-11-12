"""The Emacs Lisp profile's rules, judged by the generic checks in the Eask package and Emacs Lisp sources layouts."""

from __future__ import annotations

import unittest
from pathlib import Path

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.emacs_lisp import ELISP_ECOSYSTEM
from tests.support import (
    GITHUB_WORKFLOW,
    github_job,
    github_steps,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
    uses,
)

ELISP = frozenset({"Emacs Lisp"})
TESTS = {"test/shop-test.el": "(require 'ert)\n(ert-deftest shop-total () (should (= 3 (shop-total '(1 2)))))\n"}
EMACS_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            emacs-version: ["29.4", "snapshot"]
        steps:
          - uses: purcell/setup-emacs@v8.0
            with:
              version: ${{ matrix.emacs-version }}
          - run: eask test ert test/*.el
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_sources_and_the_build_files(self) -> None:
        with temp_project({"Eask": "", "shop.el": "", "shop.elc": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (ELISP, frozenset({"Eask"})))
        self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"Cask": "", "shop-pkg.el": "", "shop.el": ""}) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset({"Cask", "package.el"}))

    def test_the_tools_directories_are_build_trees(self) -> None:
        with temp_project({"Eask": "", ".eask/30.1/x": "", ".cask/x": ""}) as root:
            self.assertTrue(is_build_tree(Path(root, ".eask")))
            self.assertTrue(is_build_tree(Path(root, ".cask")))
            self.assertFalse(is_build_tree(Path(root, "test")))

    def test_ci_usage(self) -> None:
        for text in (
            "eask test ert",
            "cask exec ert-runner",
            "emacs -batch -l shop.el",
            "uses: purcell/setup-emacs@v8.0",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(ELISP_ECOSYSTEM, text))
        self.assertFalse(uses(ELISP_ECOSYSTEM, "npm test"))


class EmacsLispTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, ELISP_ECOSYSTEM)

    def test_the_runners_run_the_ert_and_buttercup_tests(self) -> None:
        for line in (
            "eask test ert test/*.el",
            "eask test buttercup",
            "cask exec ert-runner",
            "cask exec buttercup -L .",
            "emacs -Q -batch -L . -l test/shop-test.el -f ert-run-tests-batch-and-exit",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        buttercup = {
            "tests/shop-test.el": '(describe "total"\n  (it "sums" (expect (shop-total \'(1 2)) :to-equal 3)))\n'
        }
        self.assertEqual(self._run(tests_run, {**buttercup, **_ci("eask test buttercup")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TESTS, **_ci("eask compile")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("eask test ert test/*.el")).status, Status.FAIL)

    def test_undercover_counts_lines_when_the_tests_set_it_up(self) -> None:
        passed = Result.passed(
            "line coverage is reported with undercover.el",
            "consider failing CI when line coverage falls below a threshold",
        )
        configured = {
            "test/shop-test.el": '(when (require \'undercover nil t)\n  (undercover "*.el"))\n(ert-deftest t ())\n'
        }
        self.assertEqual(self._run(coverage, {**configured, **_ci("eask test ert test/*.el")}), passed)
        forced = github_job("ubuntu-latest", "UNDERCOVER_FORCE=true cask exec ert-runner")
        self.assertEqual(self._run(coverage, forced), passed)
        self.assertEqual(self._run(coverage, configured).status, Status.FAIL)
        self.assertEqual(self._run(coverage, {**TESTS, **_ci("eask test ert test/*.el")}).status, Status.FAIL)

    def test_package_lint_and_checkdoc_are_the_lints(self) -> None:
        passed = Result.passed("strict Emacs Lisp lints are enabled: package-lint, checkdoc")
        self.assertEqual(self._run(compiler_warnings, _ci("eask lint package", "eask lint checkdoc")), passed)
        self.assertEqual(self._run(compiler_warnings, _ci("melpazoid")), passed)
        only_one = self._run(compiler_warnings, _ci("eask lint package"))
        self.assertEqual(only_one, Result.warned("missing Emacs Lisp lints: checkdoc", "found package-lint"))
        self.assertEqual(self._run(static_analysis, _ci("eask lint checkdoc")), Result.passed("checkdoc runs"))
        self.assertEqual(self._run(compiler_warnings, _ci("eask compile")).status, Status.FAIL)

    def test_byte_compile_warnings_fail_the_build(self) -> None:
        strict = self._run(warnings_as_errors, _ci("eask compile --strict"))
        self.assertEqual(strict, Result.passed("warnings are treated as errors with eask compile --strict"))
        on_the_line = _ci("emacs -batch --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile shop.el")
        self.assertEqual(self._run(warnings_as_errors, on_the_line).status, Status.PASS)
        makefile = {
            "Makefile": "compile:\n\temacs -batch --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile\n"
        }
        self.assertEqual(self._run(warnings_as_errors, makefile).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("eask compile")).status, Status.FAIL)

    def test_the_outputs_of_the_package_and_its_tool_must_be_ignored(self) -> None:
        eask = {".gitignore": "*.elc\n*-autoloads.el\n.eask/\n"}
        self.assertEqual(run_in_layout(self, "Eask package", vcs_ignore, eask).status, Status.PASS)
        result = run_in_layout(self, "Eask package", vcs_ignore, {".gitignore": "*.elc\n*-autoloads.el\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn(".eask/", " ".join((result.message, *result.details)))
        sources = {".gitignore": "*.elc\n*-autoloads.el\n"}
        self.assertEqual(run_in_layout(self, "Emacs Lisp sources", vcs_ignore, sources).status, Status.PASS)
        self.assertEqual(
            run_in_layout(self, "Emacs Lisp sources", vcs_ignore, {".gitignore": "*.elc\n"}).status, Status.WARN
        )

    def test_the_platform_matrix_counts_emacs_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: EMACS_MATRIX})
        self.assertIn("2 Emacs version(s) (29.4, snapshot)", result.message)
        for files, version in (
            (_ci("docker run silex/emacs:30.1 eask test ert"), "30.1"),
            (_ci("eask test ert test/*.el"), "default"),
        ):
            with self.subTest(files=files):
                self.assertIn(f"1 Emacs version(s) ({version})", self._run(platform_matrix, files).message)
        other = github_steps("uses: fortran-lang/setup-fortran@v1", "run: eask test ert")
        other[GITHUB_WORKFLOW] = other[GITHUB_WORKFLOW].replace(
            '"uses": "fortran-lang/setup-fortran@v1"',
            '"uses": "fortran-lang/setup-fortran@v1", "with": {"version": "14"}',
        )
        self.assertIn("1 Emacs version(s) (default)", self._run(platform_matrix, other).message)
