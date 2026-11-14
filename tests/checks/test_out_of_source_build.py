"""The out-of-source-build check (and what the three build layout checks share): in-source builds are prevented, or the
check warns; a project without CMake or Meson build files is not judged."""

from __future__ import annotations

import unittest

from project_validator.checks.compile_commands import compile_commands
from project_validator.checks.out_of_source_build import out_of_source_build
from project_validator.checks.top_level_guard import top_level_guard
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CMAKE_PROJECT,
    WELL_CONFIGURED,
    c_family_layouts_built_with,
    in_cmake_project,
    in_meson_project,
    layout_project,
    make_context,
    run_in_layout,
    temp_project,
)

IN_SOURCE = 'if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)\n  message(FATAL_ERROR "no")\nendif()\n'
GUARDED = "if(PROJECT_IS_TOP_LEVEL)\n  include(CTest)\n  add_subdirectory(test)\nendif()\n"


class BuildLayoutTests(unittest.TestCase):
    def test_declare_the_languages_they_judge(self) -> None:
        for selected in (out_of_source_build, compile_commands, top_level_guard):
            self.assertEqual(selected.languages, C_FAMILY)

    def test_the_well_configured_project_passes_and_the_bare_one_warns(self) -> None:
        for selected in (out_of_source_build, compile_commands, top_level_guard):
            for layout in c_family_layouts_built_with(selected, "CMake"):
                with layout_project(self, layout, WELL_CONFIGURED) as root:
                    self.assertEqual(selected.run(make_context(root)).status, Status.PASS, (selected.name, layout.name))
            with self.subTest(check=selected.name):
                self.assertEqual(run_in_layout(self, "CMake C++", selected, BARE_PROJECT).status, Status.WARN)

    def test_a_project_without_build_files_is_not_judged(self) -> None:
        for selected in (out_of_source_build, compile_commands, top_level_guard):
            with temp_project({"include/lib.hpp": "", "README.md": ""}) as root:
                self.assertEqual(selected.run(make_context(root)), Result.skipped("no CMake or Meson build files"))


class OutOfSourceBuildTests(unittest.TestCase):
    def test_a_comparison_of_the_directories_passes(self) -> None:
        found = "a check that the source and binary directories differ"
        for guard in (
            IN_SOURCE,
            'if("${CMAKE_SOURCE_DIR}" STREQUAL "${CMAKE_BINARY_DIR}")\n  message(FATAL_ERROR "no")\nendif()\n',
            'if(PROJECT_BINARY_DIR PATH_EQUAL PROJECT_SOURCE_DIR)\n  message(FATAL_ERROR "no")\nendif()\n',
            "if(NOT EXISTS build)\nelseif(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_CURRENT_BINARY_DIR)\nendif()\n",
            "include(cmake/PreventInSourceBuilds.cmake)\n",
        ):
            with self.subTest(guard=guard):
                files = {"cmake/PreventInSourceBuilds.cmake": IN_SOURCE} if "include" in guard else {}
                result = run_in_layout(
                    self, "CMake C++", out_of_source_build, {"CMakeLists.txt": CMAKE_PROJECT + guard, **files}
                )
                self.assertEqual(result, Result.passed(f"in-source builds are prevented by {found}"))

    def test_the_disabling_variables_pass_and_nothing_warns(self) -> None:
        for build in ("set(CMAKE_DISABLE_IN_SOURCE_BUILD ON)\n", "set(CMAKE_DISABLE_SOURCE_CHANGES ON)\n"):
            with self.subTest(build=build):
                self.assertEqual(in_cmake_project(self, out_of_source_build, build).status, Status.PASS)
        result = in_cmake_project(self, out_of_source_build, "set(CMAKE_DISABLE_IN_SOURCE_BUILD OFF)\n")
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "in-source builds are not prevented")
        self.assertIn("PreventInSourceBuilds.cmake", result.details[0])

    def test_meson_builds_out_of_source(self) -> None:
        self.assertEqual(
            in_meson_project(self, out_of_source_build),
            Result.passed("in-source builds are prevented by Meson, which builds out of source"),
        )
