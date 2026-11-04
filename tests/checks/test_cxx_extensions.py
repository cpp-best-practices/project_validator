import unittest

from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    c_family_layouts_built_with,
    layout_project,
    make_context,
    run_in_every_layout,
    temp_project,
)


class CxxExtensionsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, cxx_extensions, files, c_family_layouts_built_with(cxx_extensions, "CMake"))

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


class MesonCxxExtensionsTests(unittest.TestCase):
    def _run(self, meson: str, files: dict[str, str] | None = None) -> Result:
        with temp_project({"meson.build": meson, "src/main.c": "", **(files or {})}) as root:
            return cxx_extensions.run(make_context(root))

    def test_fails_when_the_standard_is_never_set(self) -> None:
        for layout in c_family_layouts_built_with(cxx_extensions, "Meson"):
            with layout_project(self, layout) as root:
                result = cxx_extensions.run(make_context(root))
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn("never disabled", result.message)

    def test_passes_with_a_standard_cpp_std(self) -> None:
        result = self._run("project('app', 'cpp', default_options: ['cpp_std=c++20'])\n")
        self.assertEqual(result, Result.passed("C++ compiler extensions are disabled with cpp_std=c++20"))

    def test_passes_with_cpp_std_set_in_ci(self) -> None:
        result = self._run(
            "project('app', 'cpp')\n", {GITHUB_WORKFLOW: "steps:\n  - run: meson setup b -Dcpp_std=c++23\n"}
        )
        self.assertEqual(result.status, Status.PASS)

    def test_fails_with_gnu_or_vc_standards(self) -> None:
        for std in ("gnu++20", "vc++latest"):
            with self.subTest(std=std):
                result = self._run(f"project('app', 'cpp', default_options: ['cpp_std={std}'])\n")
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn(f"enabled with cpp_std={std}", result.message)

    def test_c_projects_need_a_standard_c_std(self) -> None:
        self.assertEqual(self._run("project('app', 'c', default_options: ['c_std=c17'])\n").status, Status.PASS)
        self.assertEqual(self._run("project('app', 'c', default_options: ['c_std=gnu17'])\n").status, Status.FAIL)
        result = self._run("project('app', 'c')\n")
        self.assertIn("c_std=c17", result.message)

    def test_cmake_settings_do_not_count_in_a_meson_project(self) -> None:
        result = self._run("project('app', 'cpp')\n", {"CMakePresets.json": '{"CMAKE_CXX_EXTENSIONS": false}'})
        self.assertEqual(result.status, Status.FAIL)
