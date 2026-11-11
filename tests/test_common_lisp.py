"""The Common Lisp profile's rules, judged by the generic checks in the ASDF system and Lisp sources layouts."""

import json
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
from project_validator.ecosystems.common_lisp import LISP_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, make_context, run_as, temp_project

LISP = frozenset({"Common Lisp"})
TESTS = {"tests/main.lisp": "(def-suite shop-suite)\n(test total (is (= 6 (shop:total '(1 2 3)))))\n"}
TEST_SYSTEM = 'sbcl --non-interactive --eval "(asdf:test-system :shop)"'
LISP_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            lisp: [sbcl-bin, ccl-bin]
        env:
          LISP: ${{ matrix.lisp }}
        steps:
          - uses: 40ants/setup-lisp@v4
          - run: ros run --eval '(asdf:test-system :shop)'
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _action(name: str, **inputs: str) -> dict[str, str]:
    """A GitHub job with one step using the action `name` with `inputs`."""
    step: dict[str, object] = {"uses": name}
    if inputs:
        step["with"] = inputs
    job = {"runs-on": "ubuntu-latest", "steps": [step]}
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"test": job}})}


class RecognitionTests(unittest.TestCase):
    def test_sources_and_system_definitions(self) -> None:
        with temp_project({"src/shop.lisp": "", "src/kernel.cl": "", "roswell/shop.ros": "", "shop.asd": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (LISP, frozenset({"ASDF"})))
        self.assertEqual(structure.unrecognised_suffixes, ())
        # A .cl file alone may be OpenCL.
        with temp_project({"kernels/add.cl": "__kernel void add() {}\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())

    def test_qlots_directory_is_a_build_tree(self) -> None:
        with temp_project({"shop.asd": "", ".qlot/setup.lisp": ""}) as root:
            self.assertTrue(is_build_tree(Path(root, ".qlot")))
            self.assertFalse(is_build_tree(Path(root, "src")))

    def test_ci_usage(self) -> None:
        for text in (TEST_SYSTEM, "ros install sbcl-bin", "qlot exec rove shop.asd", "uses: 40ants/setup-lisp@v4"):
            with self.subTest(text=text):
                self.assertTrue(LISP_ECOSYSTEM.used_by(text))
        self.assertFalse(LISP_ECOSYSTEM.used_by("npm test"))


class CommonLispTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, LISP_ECOSYSTEM)

    def test_the_test_op_runs_the_tests(self) -> None:
        for line in (TEST_SYSTEM, "ros run --eval '(rove:run :shop/tests)'", "qlot exec rove shop.asd"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        action = {**TESTS, **_action("40ants/run-tests@v2", **{"asdf-system": "shop"})}
        self.assertEqual(self._run(tests_run, action).status, Status.PASS)
        parachute = {"t/shop.lisp": "(define-test total (is = 6 (shop:total '(1 2 3))))\n", **_ci(TEST_SYSTEM)}
        self.assertEqual(self._run(tests_run, parachute).status, Status.PASS)
        self.assertEqual(
            self._run(tests_run, {**TESTS, **_ci("sbcl --eval '(asdf:load-system :shop)'")}).status, Status.WARN
        )
        self.assertEqual(self._run(tests_run, _ci(TEST_SYSTEM)).status, Status.FAIL)

    def test_sb_cover_counts_branches(self) -> None:
        passed = Result.passed("branch coverage is reported with sb-cover")
        on_the_line = _ci("sbcl --eval '(require :sb-cover)' --eval '(asdf:test-system :shop)'")
        self.assertEqual(self._run(coverage, on_the_line), passed)
        scripted = {"ci/coverage.lisp": "(require :sb-cover)\n(asdf:test-system :shop)\n", **_ci(TEST_SYSTEM)}
        self.assertEqual(self._run(coverage, scripted), passed)
        token = _action("40ants/run-tests@v2", **{"asdf-system": "shop", "coveralls-token": "${{ secrets.T }}"})
        self.assertEqual(self._run(coverage, token), passed)
        self.assertEqual(
            self._run(coverage, _action("40ants/run-tests@v2", **{"asdf-system": "shop"})).status, Status.FAIL
        )
        self.assertEqual(self._run(coverage, _ci(TEST_SYSTEM)).status, Status.FAIL)

    def test_sblint_is_the_warning_set_and_the_analyzer(self) -> None:
        self.assertEqual(
            self._run(compiler_warnings, _ci("qlot exec sblint shop.asd")),
            Result.passed("strict Lisp compiler lints are enabled: sblint"),
        )
        self.assertEqual(self._run(static_analysis, _ci("sblint shop.asd")), Result.passed("sblint runs"))
        self.assertEqual(self._run(compiler_warnings, _ci("ros install cxxxr/sblint")).status, Status.FAIL)
        self.assertEqual(self._run(static_analysis, _ci(TEST_SYSTEM)).status, Status.FAIL)

    def test_compiler_warnings_fail_the_build_with_uiop(self) -> None:
        passed = Result.passed("warnings are treated as errors with uiop:*compile-file-warnings-behaviour* :error")
        on_the_line = _ci(
            "sbcl --eval '(setf uiop:*compile-file-warnings-behaviour* :error)' --eval '(asdf:test-system :shop)'"
        )
        self.assertEqual(self._run(warnings_as_errors, on_the_line), passed)
        in_a_script = {"ci/build.lisp": "(setf uiop:*compile-file-failure-behaviour* :error)\n"}
        self.assertEqual(self._run(warnings_as_errors, in_a_script), passed)
        self.assertEqual(self._run(warnings_as_errors, _ci(TEST_SYSTEM)).status, Status.FAIL)

    def test_compiled_files_and_qlots_directory_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.fasl\n.qlot/\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.lx64fsl\n/.qlot\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.fasl\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_implementations(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: LISP_MATRIX})
        self.assertIn("2 Lisp implementation(s) (ccl-bin, sbcl-bin)", result.message)
        for line, implementation in (
            ("ros install ecl && ros run --eval '(asdf:test-system :shop)'", "ecl"),
            ("ros use ccl-bin/1.12.2", "ccl-bin/1.12.2"),
            ("docker run clfoundation/sbcl:2.3.0 sbcl --eval '(asdf:test-system :shop)'", "sbcl:2.3.0"),
            (TEST_SYSTEM, "default"),
        ):
            with self.subTest(line=line):
                self.assertIn(
                    f"1 Lisp implementation(s) ({implementation})", self._run(platform_matrix, _ci(line)).message
                )
