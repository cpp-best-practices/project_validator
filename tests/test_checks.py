import json
import shutil
import unittest

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.ci_present import ci_present
from project_validator.checks.coverage import coverage
from project_validator.checks.ctest_runs import ctest_runs
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
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


def _workflow(matrix: dict[str, object], configure: str) -> dict[str, str]:
    job = {"runs-on": "${{ matrix.os }}", "strategy": {"matrix": matrix}, "steps": [{"run": configure}]}
    return {".github/workflows/ci.yml": json.dumps({"jobs": {"build": job}})}


class CiBuildTypesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return ci_build_types.run(make_context(root))

    def test_fails_without_ci(self) -> None:
        self.assertEqual(ci_build_types.run(make_context(FIXTURES / "bare_project")).status, Status.FAIL)

    def test_fails_without_a_known_platform(self) -> None:
        result = self._run({".github/workflows/ci.yml": "jobs: {}\n"})
        self.assertEqual(result.message, "no OS/compiler combination found in CI configuration")

    def test_passes_with_debug_and_release_with_and_without_sanitizers_everywhere(self) -> None:
        result = ci_build_types.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS, result.details)
        self.assertEqual(
            result.message,
            "all 5 OS/compiler combination(s) build Debug and Release, each with and without sanitizers",
        )

    def test_fails_when_build_type_is_never_specified(self) -> None:
        result = self._run(_workflow({"os": ["ubuntu-latest"]}, "cmake -S . -B build"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("1 of 1 OS/compiler combination(s)", result.message)
        self.assertIn("linux / gcc: no build type specified", result.details)

    def test_fails_when_only_one_kind_is_built(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "sanitize": ["ON", "OFF"]}
        result = self._run(
            _workflow(matrix, "cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_SANITIZERS=${{ matrix.sanitize }}")
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("linux / gcc: missing Debug, Debug + sanitizers", result.details)

    def test_fails_when_sanitizers_are_never_enabled(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "build_type": ["Debug", "Release"]}
        result = self._run(_workflow(matrix, "cmake -DCMAKE_BUILD_TYPE=${{ matrix.build_type }}"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("linux / gcc: missing Debug + sanitizers, Release + sanitizers", result.details)

    def test_every_combination_needs_all_four_builds(self) -> None:
        matrix = {
            "os": ["ubuntu-latest"],
            "compiler": ["gcc", "clang"],
            "build_type": ["Debug", "Release"],
            "sanitize": ["ON", "OFF"],
            "exclude": [{"compiler": "clang", "sanitize": "ON"}],
        }
        configure = (
            "cmake -DCMAKE_CXX_COMPILER=${{ matrix.compiler }} -DCMAKE_BUILD_TYPE=${{ matrix.build_type }}"
            " -DENABLE_SANITIZERS=${{ matrix.sanitize }}"
        )
        result = self._run(_workflow(matrix, configure))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("1 of 2 OS/compiler combination(s)", result.message)
        self.assertEqual(result.details, ("linux / clang: missing Debug + sanitizers, Release + sanitizers",))

    def test_cmake_template_maintainer_mode_toggles_sanitizers(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "build_type": ["Release", "Debug"], "maintainer": ["ON", "OFF"]}
        configure = (
            "cmake -DCMAKE_BUILD_TYPE:STRING=${{matrix.build_type}}"
            " -D${{ env.PROJECT_NAME }}_PACKAGING_MAINTAINER_MODE:BOOL=${{matrix.maintainer}}"
        )
        self.assertEqual(self._run(_workflow(matrix, configure)).status, Status.PASS)


class SecurityScanningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return security_scanning.run(make_context(root))

    def test_warns_without_ci(self) -> None:
        result = security_scanning.run(make_context(FIXTURES / "bare_project"))
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_code_scanning(self) -> None:
        result = self._run({".github/workflows/ci.yml": "steps:\n  - run: ctest --test-dir build\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no code security scanning", result.message)

    def test_passes_with_codeql(self) -> None:
        result = security_scanning.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with CodeQL")

    def test_passes_with_the_gitlab_sast_template(self) -> None:
        result = self._run({".gitlab-ci.yml": "include:\n  - template: Security/SAST.gitlab-ci.yml\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with GitLab SAST")

    def test_codeql_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# uses: github/codeql-action/analyze@v3\n"})
        self.assertEqual(result.status, Status.WARN)
