import unittest

from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Result, Status
from project_validator.structure import C_FAMILY
from tests.support import BARE_PROJECT, CI_FILES, WELL_CONFIGURED, run_in_every_layout


class WarningsAsErrorsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, warnings_as_errors, files)

    # -Werror and /WX are C/C++ compiler flags; other languages' equivalents are judged by compiler-warnings.
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(warnings_as_errors.languages, C_FAMILY)

    def test_fails_without_warnings_as_errors(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("warnings are not treated as errors", result.message)
        self.assertIn("CMAKE_COMPILE_WARNING_AS_ERROR", result.details[0])

    def test_passes_with_werror_in_an_optional_configuration(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_passes_with_msvc_wx(self) -> None:
        result = self._run({"cmake/CompilerWarnings.cmake": "set(MSVC_WARNINGS /W4 /WX)\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "warnings are treated as errors with /WX")

    def test_passes_with_the_cmake_variable(self) -> None:
        result = self._run({"CMakeLists.txt": "set(CMAKE_COMPILE_WARNING_AS_ERROR ON)\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "warnings are treated as errors with COMPILE_WARNING_AS_ERROR")

    def test_passes_with_the_target_property(self) -> None:
        result = self._run({"CMakeLists.txt": "set_target_properties(app PROPERTIES COMPILE_WARNING_AS_ERROR TRUE)\n"})
        self.assertEqual(result.status, Status.PASS)

    def test_passes_with_the_cmake_variable_set_from_any_ci(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                configure = "steps:\n  - run: cmake -S . -B build -DCMAKE_COMPILE_WARNING_AS_ERROR:BOOL=ON\n"
                result = self._run({path: configure})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, "warnings are treated as errors with COMPILE_WARNING_AS_ERROR")

    def test_passes_with_werror_in_any_ci(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: 'steps:\n  - run: cmake -S . -B build -DCMAKE_CXX_FLAGS="-Wall -Werror"\n'})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, "warnings are treated as errors with -Werror")

    def test_passes_with_the_cmake_variable_in_a_preset(self) -> None:
        for value in ('"ON"', "true", '{"type": "BOOL", "value": "ON"}'):
            with self.subTest(value=value):
                variables = f'{{"CMAKE_COMPILE_WARNING_AS_ERROR": {value}}}'
                preset = f'{{"configurePresets": [{{"cacheVariables": {variables}}}]}}'
                result = self._run({"CMakePresets.json": preset})
                self.assertEqual(result.status, Status.PASS)

    def test_reports_every_form_found(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Werror /WX)\n"})
        self.assertEqual(result.message, "warnings are treated as errors with -Werror, /WX")

    def test_disabled_or_partial_settings_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    set(CMAKE_COMPILE_WARNING_AS_ERROR OFF)
                    add_compile_options(-Werror=return-type -Wno-error /WX:NO)
                    """,
                "CMakePresets.json": """\
                    {"configurePresets": [{"cacheVariables": {"CMAKE_COMPILE_WARNING_AS_ERROR": false}}]}
                    """,
            }
        )
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_werror_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# add_compile_options(-Werror)\n"})
        self.assertEqual(result.status, Status.FAIL)
