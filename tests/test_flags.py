"""Compiler flags as practice requirements, shared by every compiled language."""

import unittest

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.core import Status
from project_validator.facts.flags import flag_requirement, literal_starts
from project_validator.tools.toolchains import Flag
from tests.support import github_job, run_in_layout


class FlagTests(unittest.TestCase):
    def test_hints_are_the_literal_start_of_each_spelling(self) -> None:
        self.assertEqual(literal_starts("-Wpedantic|-pedantic(?:-errors)?"), ("-Wpedantic", "-pedantic"))
        self.assertEqual(literal_starts(r"-std=f(?:2008|2018)|-stand[\s:]f18"), ("-std=f", "-stand"))
        self.assertIsNone(literal_starts("[/-]WX"))
        requirement = flag_requirement(Flag("-Wall", "-Wall"), frozenset({"C"}))
        self.assertEqual(requirement.hints, ("-Wall",))
        unhinted = flag_requirement(Flag("/WX", "[/-]WX"), frozenset({"C"}), configured=("x",), configured_hints=("x",))
        self.assertEqual(unhinted.hints, ())

    def test_settings_that_set_a_flag_need_hints(self) -> None:
        with self.assertRaises(ValueError):
            flag_requirement(Flag("-Werror", "-Werror"), frozenset({"C"}), configured=("--werror",))

    def test_a_flag_counts_as_an_options_value(self) -> None:
        ci = github_job("ubuntu-latest", "make CFLAGS=-Wall CXXFLAGS=-Wextra", "gcc -Wpedantic -Wshadow -Wconversion")
        result = run_in_layout(self, "CMake C++", compiler_warnings, {"CMakeLists.txt": "", **ci})
        self.assertEqual(result.status, Status.PASS)
