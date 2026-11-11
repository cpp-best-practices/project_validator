"""The R profile's rules, judged by the generic checks in the R package and R scripts layouts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.function_limits import function_limits
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.r import R_ECOSYSTEM, r_code
from tests.support import GITHUB_WORKFLOW, command, github_job, github_steps, make_context, run_as, temp_project

R = frozenset({"R"})
TESTS = {"tests/testthat/test-shop.R": 'test_that("total sums", {\n  expect_equal(total(c(1, 2)), 3)\n})\n'}
IGNORED = ".Rhistory\n.RData\n.Rproj.user/\n*.Rcheck/\n"
R_MATRIX = """\
    jobs:
      check:
        runs-on: ${{ matrix.config.os }}
        strategy:
          matrix:
            config:
              - {os: macos-latest, r: release}
              - {os: ubuntu-latest, r: devel}
              - {os: ubuntu-latest, r: oldrel-1}
        steps:
          - uses: r-lib/actions/setup-r@v2
            with:
              r-version: ${{ matrix.config.r }}
          - uses: r-lib/actions/check-r-package@v2
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _rscript_step(script: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """A GitHub job with one step whose `shell: Rscript {0}` runs `script`."""
    step: dict[str, object] = {"run": script, "shell": "Rscript {0}"}
    if env:
        step["env"] = env
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": [step]}}})}


def _action(name: str, **inputs: str) -> dict[str, str]:
    step = {"uses": name, "with": inputs} if inputs else {"uses": name}
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": [step]}}})}


class RecognitionTests(unittest.TestCase):
    def test_a_description_with_a_package_field_is_an_r_package(self) -> None:
        with temp_project({"DESCRIPTION": "Package: shop\nVersion: 0.1\n", "R/shop.R": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (R, frozenset({"R package"})))
        with temp_project({"DESCRIPTION": "A text file of another project.\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())

    def test_suffixes_of_the_ecosystem(self) -> None:
        files = {"R/shop.R": "", "scripts/old.r": "", "vignettes/shop.Rmd": "", "man/total.Rd": "", "shop.Rproj": ""}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, R)
        self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"scripts/old.r": ""}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())

    def test_check_directories_are_build_trees(self) -> None:
        with temp_project({"DESCRIPTION": "Package: shop\n", "shop.Rcheck/00check.log": ""}) as root:
            self.assertTrue(is_build_tree(Path(root, "shop.Rcheck")))
            self.assertFalse(is_build_tree(Path(root, "R")))

    def test_r_code_of_a_command(self) -> None:
        self.assertEqual(r_code(command('Rscript -e "covr::codecov()"')), "covr::codecov()")
        self.assertEqual(r_code(command("R -q -e 'devtools::test()' -e 'q()'")), "devtools::test()\nq()")
        self.assertEqual(r_code(command("Rscript --vanilla scripts/check.R")), "scripts/check.R")
        self.assertEqual(r_code(command("R CMD check shop_0.1.tar.gz")), "")
        self.assertEqual(r_code(command("make check")), "")

    def test_ci_usage(self) -> None:
        for text in ("Rscript -e 'covr::codecov()'", "R CMD check .", "uses: r-lib/actions/setup-r@v2"):
            with self.subTest(text=text):
                self.assertTrue(R_ECOSYSTEM.used_by(text))
        self.assertFalse(R_ECOSYSTEM.used_by("npm test"))


class RTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, R_ECOSYSTEM)

    def test_the_package_check_and_the_test_runners_run_testthat(self) -> None:
        for line in (
            "R CMD check shop_0.1.tar.gz",
            "Rscript -e 'devtools::test()'",
            "Rscript -e 'testthat::test_local()'",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        action = {**TESTS, **_action("r-lib/actions/check-r-package@v2")}
        self.assertEqual(self._run(tests_run, action).status, Status.PASS)
        step = {**TESTS, **_rscript_step("rcmdcheck::rcmdcheck(args = '--no-manual')")}
        self.assertEqual(self._run(tests_run, step).status, Status.PASS)
        tinytest = {
            "inst/tinytest/test_shop.R": "expect_equal(total(1), 1)\n",
            **_ci("Rscript -e 'tinytest::test_package(\"shop\")'"),
        }
        self.assertEqual(self._run(tests_run, tinytest).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TESTS, **_ci("R CMD build .")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("R CMD check .")).status, Status.FAIL)

    def test_covr_counts_lines(self) -> None:
        passed = Result.passed("line coverage is reported with covr")
        self.assertEqual(self._run(coverage, _ci("Rscript -e 'covr::codecov()'")), passed)
        script = "cov <- covr::package_coverage(quiet = FALSE)\nprint(cov)\ncovr::to_cobertura(cov)\n"
        self.assertEqual(self._run(coverage, _rscript_step(script)), passed)
        self.assertEqual(self._run(coverage, _ci("R CMD check .")).status, Status.FAIL)

    def test_air_checks_and_styler_rewrites(self) -> None:
        self.assertEqual(
            self._run(code_formatting, _ci("air format --check .")), Result.passed("CI enforces the air style")
        )
        self.assertEqual(self._run(code_formatting, _ci("air format .")).status, Status.FAIL)
        enforced = _ci("Rscript -e 'styler::style_pkg()'", "git diff --exit-code")
        self.assertEqual(self._run(code_formatting, enforced), Result.passed("CI enforces the styler style"))
        self.assertEqual(self._run(code_formatting, _rscript_step("styler::style_pkg()")).status, Status.FAIL)
        hooks = {
            ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/lorenzwalthert/precommit\n"
            "    rev: v0.4.3\n    hooks:\n      - id: style-files\n      - id: lintr\n",
            **_ci("pre-commit run --all-files"),
        }
        self.assertEqual(self._run(code_formatting, hooks).status, Status.PASS)
        self.assertEqual(self._run(compiler_warnings, hooks).status, Status.PASS)

    def test_lintr_must_fail_on_lints(self) -> None:
        passed = Result.passed("strict R lints are enabled: lintr, failing on lints (LINTR_ERROR_ON_LINT)")
        failing = _rscript_step("lintr::lint_package()", {"LINTR_ERROR_ON_LINT": "true"})
        self.assertEqual(self._run(compiler_warnings, failing), passed)
        self.assertEqual(
            self._run(compiler_warnings, _ci("Rscript -e 'lintr::lint_dir(error_on_lint = TRUE)'")), passed
        )
        printing = self._run(compiler_warnings, _rscript_step("lintr::lint_package()"))
        self.assertEqual(
            printing, Result.warned("missing R lints: failing on lints (LINTR_ERROR_ON_LINT)", "found lintr")
        )
        # Installing lintr is not running it.
        installing = _action("r-lib/actions/setup-r-dependencies@v2", **{"extra-packages": "any::lintr"})
        self.assertEqual(self._run(compiler_warnings, installing).status, Status.FAIL)

    def test_lintr_is_the_static_analyzer(self) -> None:
        configured = {".lintr": "linters: linters_with_defaults()\n", **_rscript_step("lintr::lint_package()")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("lintr (.lintr) runs"))
        self.assertEqual(
            self._run(static_analysis, _ci("Rscript -e 'lintr::lint_package()'")), Result.passed("lintr runs")
        )
        self.assertEqual(self._run(static_analysis, _ci("R CMD check .")).status, Status.FAIL)

    def test_the_check_fails_on_warnings_with_rcmdcheck(self) -> None:
        passed = Result.passed('warnings are treated as errors with rcmdcheck error_on = "warning"')
        self.assertEqual(self._run(warnings_as_errors, _action("r-lib/actions/check-r-package@v2")), passed)
        self.assertEqual(
            self._run(warnings_as_errors, _rscript_step('rcmdcheck::rcmdcheck(error_on = "note")')), passed
        )
        never = _action("r-lib/actions/check-r-package@v2", **{"error-on": '"never"'})
        self.assertEqual(self._run(warnings_as_errors, never).status, Status.FAIL)
        self.assertEqual(self._run(warnings_as_errors, _ci("R CMD check --as-cran .")).status, Status.FAIL)

    def test_lizard_limits_r_functions(self) -> None:
        self.assertEqual(self._run(function_limits, _ci("lizard --length 30 --warnings_only R")).status, Status.PASS)

    def test_every_session_file_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": IGNORED}).status, Status.PASS)
        self.assertEqual(
            self._run(vcs_ignore, {".gitignore": "/.Rhistory\n/.RData\n/.Rproj.user\nshop.Rcheck/\n"}).status,
            Status.PASS,
        )
        result = self._run(vcs_ignore, {".gitignore": ".Rhistory\n.RData\n.Rproj.user/\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("*.Rcheck/", " ".join((result.message, *result.details)))

    def test_the_platform_matrix_counts_r_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: R_MATRIX})
        self.assertIn("3 R version(s) (devel, oldrel-1, release)", result.message)
        for line, version in (
            ("docker run rocker/r-ver:4.4.1 Rscript -e 'covr::codecov()'", "4.4.1"),
            ("Rscript -e 'covr::codecov()'", "default"),
        ):
            with self.subTest(line=line):
                self.assertIn(f"1 R version(s) ({version})", self._run(platform_matrix, _ci(line)).message)
        self.assertIn("0 R version(s)", self._run(platform_matrix, github_steps("run: npm test")).message)
