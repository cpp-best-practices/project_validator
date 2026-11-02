import json
import os
import shutil
import unittest
from unittest import mock

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.ci_present import ci_present
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.checks.ctest_runs import ctest_runs
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, Ecosystem
from tests.support import (
    CI_FILES,
    FIXTURES,
    NON_CMAKE_C_FAMILY_LAYOUTS,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    fixture_files,
    layouts_checked_as,
    make_context,
    run_in_every_layout,
)

WELL_CONFIGURED = fixture_files("well_configured")
BARE_PROJECT = fixture_files("bare_project")
UNSTRUCTURED_CI_FILES = {
    provider: path for provider, path in CI_FILES.items() if provider not in {"GitHub Actions", "GitLab CI"}
}
GITHUB_WORKFLOW = ".github/workflows/ci.yml"


def run_as(test: unittest.TestCase, selected: Check, files: dict[str, str], *ecosystems: Ecosystem, **options: object):
    """The result of `selected` in every layout it judges as exactly `ecosystems`; it must not depend on the layout."""
    layouts = layouts_checked_as(selected, *ecosystems)
    test.assertTrue(layouts, f"no layout is judged as {[ecosystem.label for ecosystem in ecosystems]}")
    return run_in_every_layout(test, selected, files, layouts, **options)


def _github_job(runs_on: str, *steps: str, matrix: dict[str, object] | None = None) -> dict[str, str]:
    job: dict[str, object] = {"runs-on": runs_on, "steps": [{"run": step} for step in steps]}
    if matrix is not None:
        job["strategy"] = {"matrix": matrix}
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": job}})}


class CiPresentTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, ci_present, files, PROJECT_LAYOUTS)

    def test_passes_with_ci(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("GitHub Actions", result.message)

    def test_passes_with_every_ci_provider(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "jobs: {}\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, f"CI configuration found for {provider}")
                self.assertEqual(result.details, (path,))

    def test_fails_without_ci_and_lists_what_was_searched(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("GitLab CI", result.message)


class CtestRunsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, ctest_runs, files)

    def test_passes_when_tests_are_registered_and_run_in_ci(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.PASS)

    def test_fails_without_cmake_files(self) -> None:
        result = run_in_every_layout(self, ctest_runs, {"main.cpp": ""}, NON_CMAKE_C_FAMILY_LAYOUTS)
        self.assertEqual(result.message, "no CMake files found")

    def test_fails_when_ctest_is_never_enabled(self) -> None:
        self.assertIn("never enabled", self._run(BARE_PROJECT).message)

    def test_commented_out_calls_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "enable_testing()\n# add_test(NAME t COMMAND t)\n"})
        self.assertEqual(result.message, "CTest is enabled but no tests are registered")

    def test_warns_when_ci_never_runs_ctest(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                cmake = "include(CTest)\ncatch_discover_tests(tests)\n"
                result = self._run({"CMakeLists.txt": cmake, path: "jobs: {}\n"})
                self.assertEqual(result.status, Status.WARN)
                self.assertIn("catch_discover_tests", result.message)

    def test_passes_when_any_ci_provider_runs_ctest(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                cmake = "include(CTest)\nadd_test(NAME t COMMAND t)\n"
                result = self._run({"CMakeLists.txt": cmake, path: "ctest --test-dir build\n"})
                self.assertEqual(result.status, Status.PASS)

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
        return run_in_every_layout(self, coverage, files)

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
            Result.passed(
                "branch coverage is reported with cargo-llvm-cov; path coverage bonus: cargo-llvm-cov MC/DC"
            ),
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


class PlatformMatrixTests(unittest.TestCase):
    def test_fails_without_ci(self) -> None:
        self.assertEqual(run_in_every_layout(self, platform_matrix, BARE_PROJECT).status, Status.FAIL)

    def test_passes_with_an_expanded_matrix(self) -> None:
        result = run_in_every_layout(self, platform_matrix, WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn(
            "3 OS(es) (linux, macos, windows), 3 compiler(s) (clang, gcc, msvc), 5 combination(s)", result.message
        )

    def test_fails_with_a_single_platform_and_explains_why(self) -> None:
        files = {".github/workflows/ci.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"}
        result = run_in_every_layout(self, platform_matrix, files)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 operating systems (found 1)", result.message)
        self.assertIn(".github/workflows/ci.yml: a: linux / gcc (runner default)", result.details)

    def test_unstructured_providers_are_scanned_heuristically(self) -> None:
        for provider, path in UNSTRUCTURED_CI_FILES.items():
            with self.subTest(ci=provider):
                result = run_in_every_layout(self, platform_matrix, {path: "os: linux\ncompiler: gcc\n"})
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn(f"{path}: {provider} is scanned heuristically", result.details)
                self.assertIn(f"{path}: linux / gcc", result.details)


class PythonPlatformMatrixTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, platform_matrix, files, PYTHON)

    def test_passes_with_several_operating_systems_and_python_versions(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_PYTHON))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(
            result.message,
            "CI covers 3 OS(es) (linux, macos, windows), 2 Python version(s) (3.13, 3.14), 6 combination(s)",
        )

    def test_fails_with_a_single_python_version_and_explains_why(self) -> None:
        matrix = {"os": ["ubuntu-latest", "windows-latest"]}
        result = self._run(_github_job("${{ matrix.os }}", "python -m pytest", matrix=matrix))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 Python versions (found 1)", result.message)
        self.assertIn("at least 3 OS/Python version combinations (found 2)", result.message)
        self.assertIn(f"{GITHUB_WORKFLOW}: build (ubuntu-latest): linux / default", result.details)

    def test_python_versions_are_read_from_gitlab_images(self) -> None:
        pipeline = "".join(
            f"test-{version}:\n  image: python:{version}\n  script: [pytest]\n" for version in ("3.12", "3.13")
        )
        result = self._run({".gitlab-ci.yml": pipeline})
        self.assertIn("2 Python version(s) (3.12, 3.13)", result.message)
        self.assertIn("at least 2 operating systems (found 1)", result.message)

    def test_jobs_that_never_run_python_are_not_counted(self) -> None:
        result = self._run(_github_job("ubuntu-latest", "make docs"))
        self.assertIn(f"{GITHUB_WORKFLOW}: build: linux / no Python version", result.details)
        self.assertIn("0 Python version(s) (none)", result.message)


class RustPlatformMatrixTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, platform_matrix, files, RUST)

    def test_passes_with_several_operating_systems_and_toolchains(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_RUST))
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("2 Rust toolchain(s) (nightly, stable), 6 combination(s)", result.message)

    def test_unstructured_providers_are_scanned_for_toolchains(self) -> None:
        for provider, path in UNSTRUCTURED_CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "os: [linux, osx]\nscript:\n  - cargo +1.80 test\n  - cargo +nightly test\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("2 Rust toolchain(s) (1.80, nightly), 4 combination(s)", result.message)

    def test_fails_with_the_runner_default_toolchain_only(self) -> None:
        result = self._run(_github_job("ubuntu-latest", "cargo test"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 Rust toolchains (found 1)", result.message)
        self.assertIn(f"{GITHUB_WORKFLOW}: build: linux / default", result.details)


def _workflow(matrix: dict[str, object], configure: str) -> dict[str, str]:
    job = {"runs-on": "${{ matrix.os }}", "strategy": {"matrix": matrix}, "steps": [{"run": configure}]}
    return {".github/workflows/ci.yml": json.dumps({"jobs": {"build": job}})}


class CiBuildTypesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, ci_build_types, files)

    def test_fails_without_ci(self) -> None:
        self.assertEqual(self._run(BARE_PROJECT).status, Status.FAIL)

    def test_fails_without_a_known_platform(self) -> None:
        result = self._run({".github/workflows/ci.yml": "jobs: {}\n"})
        self.assertEqual(result.message, "no OS/compiler combination found in CI configuration")

    def test_passes_with_debug_and_release_with_and_without_sanitizers_everywhere(self) -> None:
        result = self._run(WELL_CONFIGURED)
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


class RustCiBuildTypesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, ci_build_types, files, RUST)

    def test_passes_with_debug_and_release_with_and_without_sanitizers_everywhere(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_RUST))
        self.assertEqual(
            result,
            Result.passed(
                "all 6 OS/Rust toolchain combination(s) build Debug and Release, each with and without sanitizers"
            ),
        )

    def test_fails_without_a_known_platform(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "jobs: {}\n"})
        self.assertEqual(result.message, "no OS/Rust toolchain combination found in CI configuration")

    def test_fails_when_only_release_is_built_without_sanitizers(self) -> None:
        release_only = "cargo +stable build --release && cargo +stable test --release"
        result = self._run(_github_job("ubuntu-latest", release_only))
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.details, ("linux / stable: missing Debug, Debug + sanitizers, Release + sanitizers",))

    def test_fails_when_no_cargo_command_builds(self) -> None:
        result = self._run(_github_job("ubuntu-latest", "cargo clippy", "cargo test --profile ci"))
        self.assertEqual(result.details, ("linux / default: no build type specified",))

    def test_python_is_not_judged(self) -> None:
        self.assertEqual(layouts_checked_as(ci_build_types, PYTHON), ())


class SecurityScanningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, security_scanning, files, PROJECT_LAYOUTS)

    def test_warns_without_ci(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_code_scanning(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "steps:\n  - run: ctest --test-dir build\n"})
                self.assertEqual(result.status, Status.WARN)
                self.assertIn("no code security scanning", result.message)

    def test_passes_with_codeql(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with CodeQL")

    def test_passes_with_the_gitlab_sast_template(self) -> None:
        result = self._run({".gitlab-ci.yml": "include:\n  - template: Security/SAST.gitlab-ci.yml\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with GitLab SAST")

    def test_codeql_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# uses: github/codeql-action/analyze@v3\n"})
        self.assertEqual(result.status, Status.WARN)


class CxxExtensionsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, cxx_extensions, files)

    def test_fails_when_extensions_are_never_disabled(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("set(CMAKE_CXX_EXTENSIONS OFF)", result.message)

    def test_passes_when_disabled_globally(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(
            result.message, "C++ compiler extensions are disabled globally with set(CMAKE_CXX_EXTENSIONS OFF)"
        )

    def test_passes_when_disabled_on_the_cmake_command_line_in_any_ci(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run(
                    {
                        "CMakeLists.txt": "project(p LANGUAGES CXX)\n",
                        path: "steps:\n  - run: cmake -S . -B build -DCMAKE_CXX_EXTENSIONS:BOOL=OFF\n",
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
        return run_in_every_layout(self, compiler_warnings, files)

    def test_fails_when_no_warning_flags_are_found(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("-Wall", result.message)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(WELL_CONFIGURED)
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


class PythonCompilerWarningsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, compiler_warnings, files, PYTHON)

    def test_warnings_as_errors_in_any_spelling_passes(self) -> None:
        spellings = {
            "python -W error": {GITHUB_WORKFLOW: "run: python3.14 -X dev -W error -m unittest\n"},
            "pytest -W error": {GITHUB_WORKFLOW: "run: pytest -q -W error\n"},
            "PYTHONWARNINGS": {GITHUB_WORKFLOW: "env:\n  PYTHONWARNINGS: error\n"},
            "pyproject filterwarnings": {"pyproject.toml": "[tool.pytest.ini_options]\nfilterwarnings = ['error']\n"},
            "pytest.ini filterwarnings": {"pytest.ini": "[pytest]\nfilterwarnings =\n    error\n"},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                expected = Result.passed("strict Python warning settings are enabled: -W error")
                self.assertEqual(self._run(files), expected)

    def test_warnings_as_errors_in_any_ci_passes(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                self.assertEqual(self._run({path: "script: python -W error -m pytest\n"}).status, Status.PASS)

    def test_fails_when_warnings_are_not_errors(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: python -W ignore -m pytest && cmake -DCMAKE_CXX_FLAGS=-Werror\n"})
        self.assertEqual(result, Result.failed("no Python warning settings found; enable at least -W error"))

    def test_c_and_cxx_flags_do_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)


class RustCompilerWarningsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, compiler_warnings, files, RUST)

    def test_passes_with_clippy_denied_warnings_and_pedantic_lints(self) -> None:
        self.assertEqual(
            self._run(dict(WELL_CONFIGURED_RUST)),
            Result.passed("strict Rust lint settings are enabled: cargo clippy -D warnings clippy::pedantic"),
        )

    def test_settings_in_cargo_and_source_files_count(self) -> None:
        files = {
            ".cargo/config.toml": '[build]\nrustflags = ["-D", "warnings"]\n',
            "src/lib.rs": "#![warn(clippy::pedantic)]\n",
            GITHUB_WORKFLOW: "run: cargo clippy\n",
        }
        self.assertEqual(self._run(files).status, Status.PASS)

    def test_denying_warnings_in_cargo_lints_or_crate_attributes_counts(self) -> None:
        settings = {"Cargo.toml": '[lints.rust]\nwarnings = "deny"\n', "src/main.rs": "#![deny(warnings)]\n"}
        for name, text in settings.items():
            with self.subTest(name):
                result = self._run({name: text, GITHUB_WORKFLOW: "run: cargo clippy -- -W clippy::pedantic\n"})
                self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_lints(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: cargo clippy -- -Dwarnings\n"})
        self.assertEqual(
            result, Result.warned("missing Rust lint settings: clippy::pedantic", "found cargo clippy -D warnings")
        )

    def test_fails_without_lint_settings(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: cargo build -Dwarnings_as_errors\n"})
        self.assertEqual(
            result,
            Result.failed("no Rust lint settings found; enable at least cargo clippy -D warnings clippy::pedantic"),
        )


class MixedLanguageCompilerWarningsTests(unittest.TestCase):
    def test_every_language_needs_strict_warnings_and_findings_are_labelled(self) -> None:
        result = run_as(self, compiler_warnings, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertTrue(result.message.startswith("C/C++: strict compiler warning flags are enabled: -Wall"))
        self.assertTrue(result.message.endswith("; Python: no Python warning settings found; enable at least -W error"))


class PythonTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str], **options: object) -> Result:
        return run_as(self, ctest_runs, files, PYTHON, **options)

    def test_passes_when_tests_exist_and_any_ci_runs_them(self) -> None:
        runners = ("python -m pytest", "python -m unittest discover", "tox -e py314", "nox -s tests")
        for provider, path in CI_FILES.items():
            for runner in runners:
                with self.subTest(ci=provider, runner=runner):
                    result = self._run({"tests/test_app.py": "", "app/io_test.py": "", path: f"script: {runner}\n"})
                    self.assertEqual(result, Result.passed("Python tests found in 2 file(s)"))

    def test_fails_without_tests(self) -> None:
        result = self._run({"tests/helpers.py": "", "tests/conftest.py": "", GITHUB_WORKFLOW: "run: pytest\n"})
        self.assertEqual(result, Result.failed("no Python tests found (test_*.py or *_test.py files)"))

    def test_warns_when_ci_never_runs_the_tests(self) -> None:
        result = self._run({"tests/test_app.py": "", GITHUB_WORKFLOW: "run: python -m build\n"})
        self.assertEqual(
            result,
            Result.warned("Python tests found in 1 file(s), but no CI configuration runs pytest, unittest, tox or nox"),
        )

    def test_build_mode_does_not_need_cmake(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_PYTHON), build=True, cmake="no-such-cmake-binary")
        self.assertEqual(result.status, Status.PASS)


class RustTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, ctest_runs, files, RUST)

    def test_passes_when_tests_exist_and_any_ci_runs_them(self) -> None:
        sources = {"src/lib.rs": "#[test]\nfn unit() {}\n", "tests/api.rs": "#[tokio::test]\nasync fn api() {}\n"}
        for provider, path in CI_FILES.items():
            for runner in ("cargo test", "cargo +nightly nextest run", "cargo llvm-cov --branch"):
                with self.subTest(ci=provider, runner=runner):
                    result = self._run({**sources, path: f"script: {runner}\n"})
                    self.assertEqual(result, Result.passed("Rust tests found in 2 file(s)"))

    def test_fails_without_tests(self) -> None:
        result = self._run({"src/lib.rs": "pub fn testing() {}\n", GITHUB_WORKFLOW: "run: cargo test\n"})
        self.assertEqual(result, Result.failed("no Rust tests found (#[test] functions)"))

    def test_warns_when_ci_never_runs_the_tests(self) -> None:
        result = self._run({"src/lib.rs": "#[test]\nfn unit() {}\n", GITHUB_WORKFLOW: "run: cargo build\n"})
        expected = Result.warned("Rust tests found in 1 file(s), but no CI configuration runs cargo test")
        self.assertEqual(result, expected)


class MixedLanguageTestsRunTests(unittest.TestCase):
    def test_every_language_needs_tests_and_findings_are_labelled(self) -> None:
        result = run_as(self, ctest_runs, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(
            result,
            Result.failed(
                "C/C++: CTest is enabled and tests are registered with add_test; "
                "Python: no Python tests found (test_*.py or *_test.py files)"
            ),
        )
