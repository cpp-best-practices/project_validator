import unittest

from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from tests.support import BARE_PROJECT, CI_FILES, WELL_CONFIGURED, run_in_every_layout


class CxxExtensionsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, cxx_extensions, files)

    # Only C/C++ has compiler extensions.
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(cxx_extensions.languages, C_FAMILY)

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
