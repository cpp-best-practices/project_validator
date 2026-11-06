import os
import shutil
import unittest
from unittest import mock

from project_validator.checks.tests_run import tests_run
from project_validator.core import Options, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    FIXTURES,
    GITHUB_WORKFLOW,
    NON_CMAKE_C_FAMILY_LAYOUTS,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    c_family_layouts_built_with,
    make_context,
    run_as,
    run_in_every_layout,
)


class CtestRunsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, tests_run, files, c_family_layouts_built_with(tests_run, "CMake"))

    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, tests_run.languages)

    def test_passes_when_tests_are_registered_and_run_in_ci(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.PASS)

    def test_a_project_without_a_build_system_fails_as_a_cmake_project(self) -> None:
        layouts = tuple(layout for layout in NON_CMAKE_C_FAMILY_LAYOUTS if not layout.build_systems)
        result = run_in_every_layout(self, tests_run, {"main.cpp": ""}, layouts)
        self.assertEqual(result.message, "no CMake files found")


class MesonTestsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        layouts = c_family_layouts_built_with(tests_run, "Meson")
        self.assertTrue(layouts)
        return run_in_every_layout(self, tests_run, files, layouts)

    def test_fails_when_meson_registers_no_tests(self) -> None:
        result = self._run({})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.message, "no tests are registered; call test() in meson.build")

    def test_commented_out_or_other_calls_do_not_count(self) -> None:
        result = self._run({"tests/meson.build": "# test('unit', exe)\nunittest_exe = executable('t', 't.cpp')\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_warns_when_ci_never_runs_meson_test(self) -> None:
        result = self._run({"tests/meson.build": "test('unit', executable('t', 't.cpp'))\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "tests are registered with test(), but no CI configuration runs meson test")

    def test_passes_when_ci_runs_meson_test(self) -> None:
        for command in ("meson test -C build", "ninja -C build test"):
            with self.subTest(command=command):
                files = {"tests/meson.build": "test('unit', exe)\n", GITHUB_WORKFLOW: f"steps:\n  - run: {command}\n"}
                self.assertEqual(self._run(files).status, Status.PASS)

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
        result = tests_run.run(make_context(FIXTURES / "buildable", Options(build=True)))
        self.assertEqual(
            result.message, "the project builds and ctest finds 1 test(s), but no CI configuration runs ctest"
        )

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "cmake or ninja is not installed")
    def test_build_mode_finds_tests_with_multi_config_generators(self) -> None:
        with mock.patch.dict(os.environ, {"CMAKE_GENERATOR": "Ninja Multi-Config"}):
            result = tests_run.run(make_context(FIXTURES / "buildable", Options(build=True)))
        self.assertIn("ctest finds 1 test(s)", result.message)

    def test_build_mode_reports_tools_that_cannot_run(self) -> None:
        result = tests_run.run(make_context(FIXTURES / "buildable", Options(build=True, cmake="no-such-cmake-binary")))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("could not run no-such-cmake-binary", result.message)


class PythonTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_as(self, tests_run, files, PYTHON, options=options)

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
        result = self._run(dict(WELL_CONFIGURED_PYTHON), Options(build=True, cmake="no-such-cmake-binary"))
        self.assertEqual(result.status, Status.PASS)


class RustTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, tests_run, files, RUST)

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
        result = run_as(self, tests_run, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(
            result,
            Result.failed(
                "C/C++: CTest is enabled and tests are registered with add_test; "
                "Python: no Python tests found (test_*.py or *_test.py files)"
            ),
        )
