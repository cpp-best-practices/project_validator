from __future__ import annotations

import unittest

from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    layout_project,
    make_context,
    run_in_layout,
    temp_project,
)

CXX_HINT = "set(CMAKE_CXX_EXTENSIONS OFF) (Meson: default_options: ['cpp_std=c++20'])"
C_HINT = "set(CMAKE_C_EXTENSIONS OFF) (Meson: default_options: ['c_std=c17'])"
CXX_FAILED = Result.failed("C++ compiler extensions are never disabled", CXX_HINT)
C_FAILED = Result.failed("C compiler extensions are never disabled", C_HINT)


def _cxx(files: dict[str, str], test: unittest.TestCase) -> Result:
    """The result in a CMake C++ project."""
    return run_in_layout(test, "CMake C++", cxx_extensions, files)


class CxxExtensionsTests(unittest.TestCase):
    # C, C++ and Fortran have compiler extensions (Fortran's dialects).
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(cxx_extensions.languages, C_FAMILY | {"Fortran"})

    def test_fails_when_extensions_are_never_disabled(self) -> None:
        self.assertEqual(_cxx(BARE_PROJECT, self), CXX_FAILED)

    def test_passes_when_disabled_globally(self) -> None:
        for layout in c_family_layouts_built_with(cxx_extensions, "CMake"):
            with layout_project(self, layout, WELL_CONFIGURED) as root:
                self.assertEqual(cxx_extensions.run(make_context(root)).status, Status.PASS)
        expected = Result.passed("C++ compiler extensions are disabled with set(CMAKE_CXX_EXTENSIONS OFF)")
        self.assertEqual(_cxx(WELL_CONFIGURED, self), expected)

    def test_passes_when_disabled_on_the_cmake_command_line(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                configure = ci_running(provider, "cmake -S . -B build -DCMAKE_CXX_EXTENSIONS:BOOL=OFF")
                result = _cxx({"CMakeLists.txt": "project(p LANGUAGES CXX)\n", **configure}, self)
                if provider in UNSTRUCTURED_CI_FILES:
                    self.assertIn(result.status, (Status.PASS, Status.ERROR))
                else:
                    expected = "C++ compiler extensions are disabled with -DCMAKE_CXX_EXTENSIONS=OFF"
                    self.assertEqual(result, Result.passed(expected))

    def test_passes_when_disabled_in_a_cmake_preset(self) -> None:
        preset = '{"configurePresets": [{"name": "ci", "cacheVariables": {"CMAKE_CXX_EXTENSIONS": false}}]}'
        result = _cxx({"CMakeLists.txt": "project(p LANGUAGES CXX)\n", "CMakePresets.json": preset}, self)
        self.assertEqual(
            result.message, "C++ compiler extensions are disabled with CMAKE_CXX_EXTENSIONS OFF in a preset"
        )

    def test_per_target_property_passes_and_suggests_the_global_setting(self) -> None:
        build = "project(p LANGUAGES CXX)\nset_target_properties(lib PROPERTIES CXX_STANDARD 20 CXX_EXTENSIONS OFF)\n"
        result = _cxx({"CMakeLists.txt": build}, self)
        self.assertEqual(
            result, Result.passed("C++ compiler extensions are disabled with CXX_EXTENSIONS OFF", CXX_PREFERENCE)
        )

    def test_set_property_on_a_target_counts(self) -> None:
        result = _cxx({"CMakeLists.txt": "set_property(TARGET app PROPERTY CXX_EXTENSIONS FALSE)\n"}, self)
        self.assertEqual(result.status, Status.PASS)

    def test_extensions_turned_on_or_commented_out_do_not_count(self) -> None:
        build = "set(CMAKE_CXX_EXTENSIONS ON)\n# set(CMAKE_CXX_EXTENSIONS OFF)\n"
        self.assertEqual(_cxx({"CMakeLists.txt": build}, self), CXX_FAILED)

    def test_disabling_only_c_extensions_does_not_cover_cxx(self) -> None:
        build = "project(p LANGUAGES C CXX)\nset(CMAKE_C_EXTENSIONS OFF)\n"
        self.assertEqual(_cxx({"CMakeLists.txt": build}, self), CXX_FAILED)

    def test_c_is_judged_by_its_own_setting(self) -> None:
        passed = run_in_layout(self, "CMake C", cxx_extensions, {"CMakeLists.txt": "set(CMAKE_C_EXTENSIONS OFF)\n"})
        self.assertEqual(passed, Result.passed("C compiler extensions are disabled with set(CMAKE_C_EXTENSIONS OFF)"))
        self.assertEqual(run_in_layout(self, "CMake C", cxx_extensions, {"CMakeLists.txt": "project(p C)\n"}), C_FAILED)


CXX_PREFERENCE = "consider set(CMAKE_CXX_EXTENSIONS OFF) so that every target has extensions disabled"


class MesonCxxExtensionsTests(unittest.TestCase):
    def _run(self, meson: str, files: dict[str, str] | None = None, source: str = "src/main.cpp") -> Result:
        with temp_project({"meson.build": meson, source: "", **(files or {})}) as root:
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
        ci = github_job("ubuntu-latest", "meson setup b -Dcpp_std=c++23")
        self.assertEqual(self._run("project('app', 'cpp')\n", ci).status, Status.PASS)

    def test_gnu_or_vc_standards_do_not_count(self) -> None:
        for std in ("gnu++20", "vc++latest"):
            with self.subTest(std=std):
                self.assertEqual(self._run(f"project('app', 'cpp', default_options: ['cpp_std={std}'])\n"), CXX_FAILED)

    def test_c_projects_need_a_standard_c_std(self) -> None:
        def run(meson: str) -> Result:
            return self._run(meson, source="src/main.c")

        self.assertEqual(run("project('app', 'c', default_options: ['c_std=c17'])\n").status, Status.PASS)
        self.assertEqual(run("project('app', 'c', default_options: ['c_std=gnu17'])\n"), C_FAILED)
        self.assertEqual(run("project('app', 'c')\n"), C_FAILED)

    def test_cmake_settings_count_wherever_they_are_set(self) -> None:
        preset = '{"configurePresets": [{"name": "ci", "cacheVariables": {"CMAKE_CXX_EXTENSIONS": false}}]}'
        self.assertEqual(self._run("project('app', 'cpp')\n", {"CMakePresets.json": preset}).status, Status.PASS)
