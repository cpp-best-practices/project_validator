import json
import unittest

from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    WELL_CONFIGURED,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    run_in_every_layout,
)

SEARCHED = (
    "warnings are not treated as errors in CI configuration or the build files (CMake files, presets, meson.build)"
)
MSVC_AND_GCC = {
    ".github/workflows/ci.yml": json.dumps(
        {
            "jobs": {
                "linux": {"runs-on": "ubuntu-latest", "steps": [{"run": "cmake -S . -B build"}]},
                "windows": {"runs-on": "windows-latest", "steps": [{"run": "cmake -S . -B build"}]},
            }
        }
    )
}


class WarningsAsErrorsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(
            self, warnings_as_errors, files, c_family_layouts_built_with(warnings_as_errors, "CMake")
        )

    # -Werror and /WX are C/C++ compiler flags, and the JVM and .NET compilers have their own; eslint --max-warnings 0
    # fails JavaScript linting on a warning, and PHPUnit's failOn* settings fail PHP tests on one. Other languages'
    # equivalents are judged by compiler-warnings.
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertLessEqual(C_FAMILY | {"JavaScript", "Java"}, warnings_as_errors.languages)
        self.assertNotIn("Python", warnings_as_errors.languages)

    def test_fails_without_warnings_as_errors(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("warnings are not treated as errors", result.message)
        self.assertIn("CMAKE_COMPILE_WARNING_AS_ERROR", result.details[0])
        self.assertEqual(
            result.message,
            SEARCHED,
        )

    def test_passes_with_werror_in_an_optional_configuration(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_passes_with_msvc_wx_when_ci_builds_with_msvc(self) -> None:
        msvc = {"CMakeLists.txt": "if(MSVC)\n  add_compile_options(/W4 /WX)\nendif()\n"}
        result = self._run({**msvc, **github_job("windows-latest", "cmake -S . -B build")})
        self.assertEqual(result, Result.passed("warnings are treated as errors with /WX"))
        self.assertEqual(self._run(msvc).status, Status.FAIL)

    def test_passes_with_the_cmake_variable(self) -> None:
        result = self._run({"CMakeLists.txt": "set(CMAKE_COMPILE_WARNING_AS_ERROR ON)\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_passes_with_the_target_property(self) -> None:
        result = self._run({"CMakeLists.txt": "set_target_properties(app PROPERTIES COMPILE_WARNING_AS_ERROR TRUE)\n"})
        self.assertEqual(result.status, Status.PASS)

    def test_passes_with_the_cmake_variable_set_from_any_ci(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                configure = ci_running(provider, "cmake -S . -B build -DCMAKE_COMPILE_WARNING_AS_ERROR:BOOL=ON")
                self.assertEqual(self._run(configure), Result.passed("warnings are treated as errors with -Werror"))

    def test_passes_with_werror_in_any_ci(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "cmake -S . -B build -DCMAKE_CXX_FLAGS=-Werror"))
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_passes_with_the_cmake_variable_in_a_preset(self) -> None:
        for value in ('"ON"', "true", '{"type": "BOOL", "value": "ON"}'):
            with self.subTest(value=value):
                variables = f'{{"CMAKE_COMPILE_WARNING_AS_ERROR": {value}}}'
                preset = f'{{"configurePresets": [{{"name": "ci", "cacheVariables": {variables}}}]}}'
                result = self._run({"CMakePresets.json": preset})
                self.assertEqual(result.status, Status.PASS)

    def test_reports_every_form_found(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Werror /WX)\n", **MSVC_AND_GCC})
        self.assertEqual(result.message, "warnings are treated as errors with -Werror, /WX")

    def test_disabled_or_partial_settings_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    set(CMAKE_COMPILE_WARNING_AS_ERROR OFF)
                    add_compile_options(-Werror=return-type -Wno-error /WX:NO)
                    """,
                "CMakePresets.json": """\
                    {"configurePresets": [{"name": "ci", "cacheVariables": {"CMAKE_COMPILE_WARNING_AS_ERROR": false}}]}
                    """,
            }
        )
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_werror_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# add_compile_options(-Werror)\n"})
        self.assertEqual(result.status, Status.FAIL)


class MesonWarningsAsErrorsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        layouts = c_family_layouts_built_with(warnings_as_errors, "Meson")
        self.assertTrue(layouts)
        return run_in_every_layout(self, warnings_as_errors, files, layouts)

    def test_fails_without_werror(self) -> None:
        result = self._run({})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            SEARCHED,
        )
        self.assertIn("werror=true", result.details[0])

    def test_passes_with_the_werror_option(self) -> None:
        cases = {
            "meson.build": "project('app', 'cpp', default_options: ['warning_level=3', 'werror=true'])\n",
        }
        for path, text in {**cases, **github_job("ubuntu-latest", "meson setup build -Dwerror=true")}.items():
            with self.subTest(path=path):
                result = self._run({path: text})
                self.assertEqual(result, Result.passed("warnings are treated as errors with -Werror"))

    def test_passes_with_werror_or_wx_as_project_arguments(self) -> None:
        result = self._run({"meson.build": "add_project_arguments('-Werror', language: 'cpp')\n"})
        self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_disabled_or_commented_out_werror_and_cmake_settings_do_not_count(self) -> None:
        result = self._run(
            {
                "meson.build": "project('app', 'cpp', default_options: ['werror=false'])\n# werror=true\n",
                "CMakePresets.json": '{"cacheVariables": {"CMAKE_COMPILE_WARNING_AS_ERROR": "ON"}}',
            }
        )
        self.assertEqual(result.status, Status.FAIL)
