import shutil
import unittest

from project_validator.checks.ci_present import ci_present
from project_validator.checks.coverage import coverage
from project_validator.checks.ctest_runs import ctest_runs
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Status
from tests.support import FIXTURES, make_context, temp_project


class CiPresentTests(unittest.TestCase):
    def test_passes_with_ci(self) -> None:
        result = ci_present.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("GitHub Actions", result.message)

    def test_fails_without_ci_and_lists_what_was_searched(self) -> None:
        result = ci_present.run(make_context(FIXTURES / "bare_project"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("GitLab CI", result.message)


class CtestRunsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return ctest_runs.run(make_context(root))

    def test_passes_when_tests_are_registered_and_run_in_ci(self) -> None:
        self.assertEqual(ctest_runs.run(make_context(FIXTURES / "well_configured")).status, Status.PASS)

    def test_fails_without_cmake_files(self) -> None:
        self.assertEqual(self._run({"main.cpp": ""}).message, "no CMake files found")

    def test_fails_when_ctest_is_never_enabled(self) -> None:
        self.assertIn("never enabled", ctest_runs.run(make_context(FIXTURES / "bare_project")).message)

    def test_commented_out_calls_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "enable_testing()\n# add_test(NAME t COMMAND t)\n"})
        self.assertEqual(result.message, "CTest is enabled but no tests are registered")

    def test_warns_when_ci_never_runs_ctest(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": "include(CTest)\ncatch_discover_tests(tests)\n",
                ".github/workflows/ci.yml": "jobs: {}\n",
            }
        )
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("catch_discover_tests", result.message)

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ctest"), "cmake is not installed")
    def test_build_mode_counts_the_tests_ctest_finds(self) -> None:
        result = ctest_runs.run(make_context(FIXTURES / "buildable", build=True))
        self.assertEqual(
            result.message, "the project builds and ctest finds 1 test(s), but no CI configuration runs ctest"
        )

    def test_build_mode_reports_tools_that_cannot_run(self) -> None:
        result = ctest_runs.run(make_context(FIXTURES / "buildable", build=True, cmake="no-such-cmake-binary"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("could not run no-such-cmake-binary", result.message)


class CoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return coverage.run(make_context(root))

    def test_fails_without_branch_coverage(self) -> None:
        result = self._run({".github/workflows/ci.yml": "run: gcovr --txt-metric line\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_branch_coverage_without_path_coverage_suggests_it(self) -> None:
        result = self._run({".gitlab-ci.yml": "script: lcov --rc branch_coverage=1\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("consider adding path coverage", result.details[0])

    def test_path_coverage_is_reported_as_a_bonus(self) -> None:
        result = coverage.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(
            result.message, "branch coverage is reported with gcovr; path coverage bonus: gcc -fcondition-coverage"
        )

    def test_python_branch_coverage_does_not_count(self) -> None:
        result = self._run({".github/workflows/ci.yml": "run: coverage run --branch -m pytest --cov-branch\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_cmake_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# llvm-cov report -show-branch-summary\n"})
        self.assertEqual(result.status, Status.FAIL)


class PlatformMatrixTests(unittest.TestCase):
    def test_fails_without_ci(self) -> None:
        self.assertEqual(platform_matrix.run(make_context(FIXTURES / "bare_project")).status, Status.FAIL)

    def test_passes_with_an_expanded_matrix(self) -> None:
        result = platform_matrix.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS)
        self.assertIn(
            "3 OS(es) (linux, macos, windows), 3 compiler(s) (clang, gcc, msvc), 5 combination(s)", result.message
        )

    def test_fails_with_a_single_platform_and_explains_why(self) -> None:
        files = {".github/workflows/ci.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"}
        with temp_project(files) as root:
            result = platform_matrix.run(make_context(root))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 operating systems (found 1)", result.message)
        self.assertIn(".github/workflows/ci.yml: a: linux / gcc (runner default)", result.details)
