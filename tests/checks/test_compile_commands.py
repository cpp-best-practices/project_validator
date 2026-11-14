"""The compile-commands check: compile_commands.json is exported, or the check warns."""

from __future__ import annotations

import unittest

from project_validator.checks.compile_commands import compile_commands
from project_validator.core import Result, Status
from tests.support import (
    CMAKE_PROJECT,
    github_job,
    in_cmake_project,
    in_meson_project,
    run_in_layout,
)

IN_SOURCE = 'if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)\n  message(FATAL_ERROR "no")\nendif()\n'
GUARDED = "if(PROJECT_IS_TOP_LEVEL)\n  include(CTest)\n  add_subdirectory(test)\nendif()\n"


class CompileCommandsTests(unittest.TestCase):
    def test_the_variable_passes_wherever_it_is_set(self) -> None:
        self.assertEqual(
            in_cmake_project(self, compile_commands, "set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n"),
            Result.passed("compile_commands.json is exported with set(CMAKE_EXPORT_COMPILE_COMMANDS ON)"),
        )
        self.assertEqual(
            in_cmake_project(self, compile_commands, 'set(CMAKE_EXPORT_COMPILE_COMMANDS ON CACHE BOOL "")\n').status,
            Status.PASS,
        )
        ci = github_job("ubuntu-latest", "cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON")
        self.assertEqual(
            in_cmake_project(self, compile_commands, "", ci),
            Result.passed("compile_commands.json is exported with -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"),
        )
        preset = '{"configurePresets": [{"name": "ci", "cacheVariables": {"CMAKE_EXPORT_COMPILE_COMMANDS": true}}]}'
        result = run_in_layout(
            self, "CMake C++", compile_commands, {"CMakeLists.txt": CMAKE_PROJECT, "CMakePresets.json": preset}
        )
        self.assertEqual(
            result.message, "compile_commands.json is exported with CMAKE_EXPORT_COMPILE_COMMANDS ON in a preset"
        )

    def test_off_or_absent_warns(self) -> None:
        for build in ("", "set(CMAKE_EXPORT_COMPILE_COMMANDS OFF)\n"):
            with self.subTest(build=build):
                result = in_cmake_project(self, compile_commands, build)
                self.assertEqual(
                    (result.status, result.message), (Status.WARN, "compile_commands.json is not exported")
                )

    def test_meson_writes_it(self) -> None:
        self.assertEqual(
            in_meson_project(self, compile_commands),
            Result.passed("compile_commands.json is exported with Meson, which writes it"),
        )
