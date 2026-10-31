import json
import os
import shutil
import unittest
from unittest import mock

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.ci_present import ci_present
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.copy_paste_detection import copy_paste_detection
from project_validator.checks.coverage import coverage
from project_validator.checks.cxx_extensions import cxx_extensions
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

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "cmake or ninja is not installed")
    def test_build_mode_finds_tests_with_multi_config_generators(self) -> None:
        with mock.patch.dict(os.environ, {"CMAKE_GENERATOR": "Ninja Multi-Config"}):
            result = ctest_runs.run(make_context(FIXTURES / "buildable", build=True))
        self.assertIn("ctest finds 1 test(s)", result.message)

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


class CopyPasteDetectionTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return copy_paste_detection.run(make_context(root))

    def test_warns_without_ci(self) -> None:
        result = copy_paste_detection.run(make_context(FIXTURES / "bare_project"))
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_copy_paste_detection(self) -> None:
        result = self._run({".github/workflows/ci.yml": "steps:\n  - run: ctest --test-dir build\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no copy-paste detection", result.message)

    def test_passes_with_pmd_cpd(self) -> None:
        result = copy_paste_detection.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs copy-paste detection with PMD CPD")

    def test_detects_known_tools(self) -> None:
        cases = (
            ("run: pmd cpd --language cpp --minimum-tokens 100 --dir src", "PMD CPD"),
            ("run: ./pmd-bin/bin/run.sh cpd --files src --language cpp", "PMD CPD"),
            ("run: npx jscpd --format cpp src", "jscpd"),
            ("run: duplo -ml 20 files.txt duplicates.txt", "Duplo"),
            ("run: java -jar simian-4.0.0.jar '**/*.cpp'", "Simian"),
            ("run: ccfx d cpp -d src", "CCFinderX"),
            ("uses: SonarSource/sonarqube-scan-action@v5", "SonarQube"),
            ("uses: SonarSource/sonarcloud-github-action@v3", "SonarQube"),
            ("run: sonar-scanner -Dsonar.projectKey=demo", "SonarQube"),
        )
        for step, tool in cases:
            with self.subTest(tool=tool, step=step):
                result = self._run({".github/workflows/ci.yml": f"steps:\n  - {step}\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, f"CI runs copy-paste detection with {tool}")

    def test_lists_every_tool_found(self) -> None:
        result = self._run({".gitlab-ci.yml": "cpd:\n  script:\n    - pmd cpd --dir src\n    - jscpd src\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs copy-paste detection with PMD CPD, jscpd")

    def test_similar_words_do_not_count(self) -> None:
        result = self._run({".github/workflows/ci.yml": "steps:\n  - run: ./duplicate.sh cpdfile duplogs\n"})
        self.assertEqual(result.status, Status.WARN)

    def test_tool_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# pmd cpd --language cpp --dir src\n"})
        self.assertEqual(result.status, Status.WARN)


class CxxExtensionsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return cxx_extensions.run(make_context(root))

    def test_fails_when_extensions_are_never_disabled(self) -> None:
        result = cxx_extensions.run(make_context(FIXTURES / "bare_project"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("set(CMAKE_CXX_EXTENSIONS OFF)", result.message)

    def test_passes_when_disabled_globally(self) -> None:
        result = cxx_extensions.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(
            result.message, "C++ compiler extensions are disabled globally with set(CMAKE_CXX_EXTENSIONS OFF)"
        )

    def test_passes_when_disabled_on_the_cmake_command_line_in_ci(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": "project(p LANGUAGES CXX)\n",
                ".github/workflows/ci.yml": "steps:\n  - run: cmake -S . -B build -DCMAKE_CXX_EXTENSIONS:BOOL=OFF\n",
            }
        )
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("-DCMAKE_CXX_EXTENSIONS=OFF", result.message)

    def test_passes_when_disabled_in_a_cmake_preset(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": "project(p LANGUAGES CXX)\n",
                "CMakePresets.json": '{"configurePresets": [{"cacheVariables": {"CMAKE_CXX_EXTENSIONS": false}}]}',
            }
        )
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("CMakePresets.json", result.message)

    def test_per_target_property_passes_and_suggests_the_global_setting(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    project(p LANGUAGES CXX)
                    add_library(lib lib.cpp)
                    set_target_properties(lib PROPERTIES CXX_STANDARD 20 CXX_EXTENSIONS OFF)
                """,
            }
        )
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "C++ compiler extensions are disabled per target with CXX_EXTENSIONS OFF")
        self.assertIn("set(CMAKE_CXX_EXTENSIONS OFF)", result.details[0])

    def test_set_property_on_a_target_counts(self) -> None:
        result = self._run({"CMakeLists.txt": "set_property(TARGET app PROPERTY CXX_EXTENSIONS FALSE)\n"})
        self.assertEqual(result.status, Status.PASS)

    def test_extensions_turned_on_or_commented_out_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "set(CMAKE_CXX_EXTENSIONS ON)\n# set(CMAKE_CXX_EXTENSIONS OFF)\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_disabling_only_c_extensions_does_not_cover_cxx(self) -> None:
        result = self._run({"CMakeLists.txt": "project(p LANGUAGES C CXX)\nset(CMAKE_C_EXTENSIONS OFF)\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_c_projects_need_c_extensions_disabled(self) -> None:
        result = self._run({"CMakeLists.txt": "project(p LANGUAGES C)\nset(CMAKE_C_EXTENSIONS OFF)\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "C compiler extensions are disabled globally with set(CMAKE_C_EXTENSIONS OFF)")

    def test_c_projects_fail_without_c_extensions_disabled(self) -> None:
        result = self._run({"CMakeLists.txt": "project(p C)\n"})
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("set(CMAKE_C_EXTENSIONS OFF)", result.message)


class CompilerWarningsTests(unittest.TestCase):
    GCC_FLAGS = "-Wall -Wextra -Wpedantic -Wshadow -Wconversion"
    MSVC_CI = "jobs:\n  build:\n    runs-on: windows-latest\n    steps:\n      - run: cmake -S . -B build\n"

    def _run(self, files: dict[str, str]):
        with temp_project(files) as root:
            return compiler_warnings.run(make_context(root))

    def test_fails_when_no_warning_flags_are_found(self) -> None:
        result = compiler_warnings.run(make_context(FIXTURES / "bare_project"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("-Wall", result.message)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = compiler_warnings.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result.status, Status.PASS, result)

    def test_passes_with_the_minimum_gcc_and_clang_flags(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("-Wconversion", result.message)

    def test_cmake_template_style_lists_count(self) -> None:
        result = self._run(
            {
                "cmake/CompilerWarnings.cmake": """\
                    set(CLANG_WARNINGS
                        -Wall
                        -Wextra # reasonable and standard
                        -Wshadow
                        -Wconversion
                        -pedantic)
                    target_compile_options(${project_name} INTERFACE ${CLANG_WARNINGS})
                """,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_flags(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Wall -Wextra)\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("-Wpedantic", result.message)
        self.assertIn("-Wshadow", result.message)
        self.assertIn("-Wconversion", result.message)
        self.assertNotIn("-Wall,", result.message)

    def test_similar_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Wshadow=local -Wno-conversion -Wall-extra)\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": f"# add_compile_options({self.GCC_FLAGS})\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_msvc_in_ci_requires_msvc_flags(self) -> None:
        result = self._run(
            {"CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n", ".github/workflows/ci.yml": self.MSVC_CI}
        )
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("/W4", result.message)
        self.assertIn("/permissive-", result.message)

    def test_msvc_in_ci_passes_with_msvc_flags(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(MSVC)
                      add_compile_options(/Wall /permissive-)
                    else()
                      add_compile_options({self.GCC_FLAGS})
                    endif()
                """,
                ".github/workflows/ci.yml": self.MSVC_CI,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_lowercase_msvc_flags_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS} /w4 /permissive-)\n",
                ".github/workflows/ci.yml": self.MSVC_CI,
            }
        )
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("/W4", result.message)

    def test_msvc_flags_are_not_required_without_msvc_in_ci(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n",
                ".github/workflows/ci.yml": "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n",
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_only_unrequired_msvc_flags_warn_rather_than_fail(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(/W4 /permissive-)\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("-Wall", result.message)
