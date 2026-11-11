"""Compiler flags as practice requirements, shared by every compiled language."""

from __future__ import annotations

import unittest

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.core import Status
from project_validator.facts.flags import errors_requirements, flag_requirement, literal_starts, warning_requirements
from project_validator.tools.toolchains import GCC_HARDENING, Flag, hardening_flags, with_fhardened
from tests.support import github_job, run_in_layout

C = frozenset({"C"})


class RequirementSetTests(unittest.TestCase):
    def test_warnings_are_also_set_by_the_build_systems_warning_level(self) -> None:
        [wall] = warning_requirements((Flag("-Wall", "-Wall"),), C)
        self.assertIn("warning_level", wall.runs.pattern if wall.runs else "")
        self.assertIn("-Dwarning_level=", wall.hints)

    def test_warnings_as_errors_are_also_set_by_the_build_systems_setting(self) -> None:
        self.assertEqual(errors_requirements(None, C), ())
        [werror] = errors_requirements(Flag("-Werror", "-Werror"), C)
        self.assertIn("COMPILE_WARNING_AS_ERROR", werror.runs.pattern if werror.runs else "")

    def test_hardening_flags_may_be_a_subset_and_gcc_also_takes_fhardened(self) -> None:
        [chosen] = hardening_flags("gcc", ("-fcf-protection",))
        self.assertEqual((chosen.name, "-fhardened" in chosen.spellings), ("-fcf-protection", True))
        [intel] = hardening_flags("intel", ("-fcf-protection",))
        self.assertEqual((intel.name, "-fhardened" in intel.spellings), ("-fcf-protection", False))
        self.assertEqual(hardening_flags("gcc"), with_fhardened(GCC_HARDENING))
        self.assertEqual(hardening_flags("unknown"), ())


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
