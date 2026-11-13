"""The top-level-guard check: the tests and developer-only settings are guarded for use as a subproject, or the check
warns."""

from __future__ import annotations

import unittest

from project_validator.checks.top_level_guard import top_level_guard
from project_validator.core import Result, Status
from tests.support import (
    CMAKE_PROJECT,
    in_cmake_project,
    in_meson_project,
    run_in_layout,
)

IN_SOURCE = 'if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)\n  message(FATAL_ERROR "no")\nendif()\n'
GUARDED = "if(PROJECT_IS_TOP_LEVEL)\n  include(CTest)\n  add_subdirectory(test)\nendif()\n"


class TopLevelGuardTests(unittest.TestCase):
    def test_a_guard_on_being_top_level_passes(self) -> None:
        for build, found in (
            (GUARDED, "PROJECT_IS_TOP_LEVEL"),
            ("if(NOT p_IS_TOP_LEVEL)\n  return()\nendif()\n", "PROJECT_IS_TOP_LEVEL"),
            (
                "if(CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR)\n  include(CTest)\nendif()\n",
                "CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR",
            ),
            (
                'if("${CMAKE_CURRENT_SOURCE_DIR}" STREQUAL "${CMAKE_SOURCE_DIR}")\n  include(CTest)\nendif()\n',
                "CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR",
            ),
            (
                "include(CMakeDependentOption)\n"
                'cmake_dependent_option(p_BUILD_TESTS "" ON "PROJECT_IS_TOP_LEVEL" OFF)\n',
                "PROJECT_IS_TOP_LEVEL",
            ),
        ):
            with self.subTest(build=build):
                self.assertEqual(
                    in_cmake_project(self, top_level_guard, build),
                    Result.passed(f"developer-only settings are guarded by {found}"),
                )

    def test_tests_included_unconditionally_warn(self) -> None:
        result = in_cmake_project(self, top_level_guard, "include(CTest)\nadd_subdirectory(test)\nif(MSVC)\nendif()\n")
        self.assertEqual((result.status, result.message), (Status.WARN, "nothing is guarded for use as a subproject"))
        self.assertIn("PROJECT_IS_TOP_LEVEL", result.details[0])

    def test_the_guarded_tests_are_still_found(self) -> None:
        # The evaluator knows the project is top level, so what the guard encloses is read.
        from project_validator.checks.tests_run import tests_run

        files = {"CMakeLists.txt": CMAKE_PROJECT + GUARDED, "test/CMakeLists.txt": "add_test(NAME t COMMAND t)\n"}
        self.assertEqual(run_in_layout(self, "CMake C++", tests_run, files).status, Status.WARN)

    def test_meson_is_subproject(self) -> None:
        build = "project('app', 'cpp')\nif not meson.is_subproject()\n  test('t', executable('t', 't.cpp'))\nendif\n"
        self.assertEqual(
            in_meson_project(self, top_level_guard, build),
            Result.passed("developer-only settings are guarded by meson.is_subproject()"),
        )
        self.assertEqual(in_meson_project(self, top_level_guard).status, Status.WARN)
