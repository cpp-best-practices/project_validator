import unittest

from project_validator.checks.coverage import coverage
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import (
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)


class CoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, coverage, files)

    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, coverage.languages)

    def test_fails_without_branch_coverage(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                self.assertEqual(self._run({path: "run: gcovr --txt-metric line\n"}).status, Status.FAIL)

    def test_branch_coverage_without_path_coverage_suggests_it(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "script: lcov --rc branch_coverage=1\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("consider adding path coverage", result.details[0])

    def test_path_coverage_is_reported_as_a_bonus(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(
            result.message, "branch coverage is reported with gcovr; path coverage bonus: gcc -fcondition-coverage"
        )

    def test_python_branch_coverage_does_not_count_for_c_and_cxx(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "run: coverage run --branch -m pytest --cov-branch\n"})
                self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_cmake_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# llvm-cov report -show-branch-summary\n"})
        self.assertEqual(result.status, Status.FAIL)


class PythonCoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, coverage, files, PYTHON)

    def test_coverage_py_branch_measurement_in_any_ci_passes_without_a_path_coverage_hint(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "script: python -m coverage run --branch -m pytest\n"})
                self.assertEqual(result, Result.passed("branch coverage is reported with coverage.py"))

    def test_pytest_cov_branch_passes(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: pytest --cov=app --cov-branch\n"})
        self.assertEqual(result.message, "branch coverage is reported with pytest-cov")

    def test_branch_setting_in_any_coverage_settings_file_passes(self) -> None:
        for name, section in {"pyproject.toml": "[tool.coverage.run]", ".coveragerc": "[run]"}.items():
            with self.subTest(name):
                result = self._run({name: f"{section}\nsource = ['app']\nbranch = True\n"})
                self.assertEqual(result.message, "branch coverage is reported with coverage.py branch = true")

    def test_line_coverage_fails(self) -> None:
        result = self._run(
            {GITHUB_WORKFLOW: "run: coverage run -m pytest\n", "setup.cfg": "[coverage:run]\nbranch = false\n"}
        )
        self.assertEqual(
            result, Result.failed("no branch coverage reporting found in CI configuration or coverage.py settings")
        )

    def test_c_and_cxx_branch_coverage_does_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)

    def test_well_configured_python_project_passes(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_PYTHON)).status, Status.PASS)


class RustCoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, coverage, files, RUST)

    def test_branch_coverage_tools_in_any_ci_pass_and_suggest_mcdc(self) -> None:
        tools = {
            "cargo-llvm-cov": "cargo +nightly llvm-cov --branch --lcov",
            "cargo-tarpaulin": "cargo tarpaulin --branch --out xml",
            "grcov": "grcov . --binary-path target/debug --branch -o lcov.info",
        }
        for provider, path in CI_FILES.items():
            for tool, command in tools.items():
                with self.subTest(ci=provider, tool=tool):
                    result = self._run({path: f"script: {command}\n"})
                    self.assertEqual(result.message, f"branch coverage is reported with {tool}")
                    self.assertEqual(result.details, ("consider adding MC/DC coverage (e.g. cargo llvm-cov --mcdc)",))

    def test_mcdc_coverage_is_reported_as_a_bonus(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_RUST))
        self.assertEqual(
            result,
            Result.passed("branch coverage is reported with cargo-llvm-cov; path coverage bonus: cargo-llvm-cov MC/DC"),
        )

    def test_line_coverage_fails(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: cargo llvm-cov --lcov\n"})
        self.assertEqual(result, Result.failed("no branch coverage reporting found in CI configuration"))


class MixedLanguageCoverageTests(unittest.TestCase):
    def test_every_language_needs_branch_coverage_and_findings_are_labelled(self) -> None:
        result = run_as(self, coverage, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "C/C++: branch coverage is reported with gcovr; path coverage bonus: gcc -fcondition-coverage; "
            "Python: no branch coverage reporting found in CI configuration or coverage.py settings",
        )

    def test_passes_when_every_language_reports_branch_coverage(self) -> None:
        files = {**WELL_CONFIGURED, "pyproject.toml": "[tool.coverage.run]\nbranch = true\n"}
        self.assertEqual(run_as(self, coverage, files, C_AND_CXX, PYTHON).status, Status.PASS)
