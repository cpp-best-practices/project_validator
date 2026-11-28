"""The policy tables (upstream #440) are data files in the package, checked against the code that uses them: a
misspelled kind, an unknown tool or check, or a malformed glob fails here, and changing a number that moves the score
without bumping `SCORE_VERSION` fails too."""

from __future__ import annotations

import re
import unittest
from fnmatch import translate
from importlib.resources import files
from pathlib import Path

from project_validator import policy_tables
from project_validator.facts.suppressions import BLANKET, FILE, GLOBAL, KEY, STYLISTIC, known_disablers
from project_validator.facts.tools import known_tools
from project_validator.plugins import discover
from project_validator.score import (
    COSMETIC,
    EXTRA,
    EXTRA_CREDIT,
    FAMILIES,
    FINDINGS,
    FLOOR,
    LEVEL_NAMES,
    LEVELS,
    POLICY_DIGEST,
    SCORE_VERSION,
    SMALLEST_STEP,
    TOP_LEVEL,
    weight_of,
)
from project_validator.strength import COVERED, DENSITY, JUSTIFIED_DENSITY, MOST_DENSITY, WEIGHTS

_DOCS = Path(__file__).resolve().parents[1] / "docs" / "score.md"


class LoadingTests(unittest.TestCase):
    def test_each_table_is_a_toml_file_shipped_in_the_package(self) -> None:
        shipped = sorted(
            entry.name for entry in (files("project_validator") / "policy").iterdir() if entry.name.endswith(".toml")
        )
        self.assertEqual(shipped, sorted(f"{name}.toml" for name in policy_tables.TABLES))

    def test_a_table_is_read_once_and_is_a_mapping(self) -> None:
        self.assertIs(policy_tables.load("score"), policy_tables.load("score"))
        self.assertIn("levels", policy_tables.load("score"))

    def test_an_unknown_table_is_an_error(self) -> None:
        with self.assertRaises(KeyError):
            policy_tables.load("weights")

    def test_the_digest_ignores_line_endings(self) -> None:
        self.assertEqual(policy_tables.digest_text("a = 1\r\nb = 2\r\n"), policy_tables.digest_text("a = 1\nb = 2\n"))
        self.assertNotEqual(policy_tables.digest_text("a = 1\n"), policy_tables.digest_text("a = 2\n"))


class ScoreVersionTests(unittest.TestCase):
    def test_changing_a_scored_table_bumps_the_score_version(self) -> None:
        """The strength, score and diagnostics files decide the numbers: change one, and bump `SCORE_VERSION` (and
        say so in the changelog), then record the new digest beside it."""
        self.assertEqual(
            policy_tables.digest(*policy_tables.SCORED),
            POLICY_DIGEST,
            f"a scored policy file changed: bump SCORE_VERSION (now {SCORE_VERSION}), add a changelog entry, and set "
            f"POLICY_DIGEST to {policy_tables.digest(*policy_tables.SCORED)!r}",
        )


class StrengthTableTests(unittest.TestCase):
    def test_every_kind_scope_and_justification_has_a_weight_from_0_to_1(self) -> None:
        expected = {
            (kind, scope, justified)
            for kind in (BLANKET, KEY, STYLISTIC)
            for scope in (GLOBAL, FILE)
            for justified in (False, True)
        }
        self.assertEqual(set(WEIGHTS), expected)
        self.assertEqual([weight for weight in WEIGHTS.values() if not 0 <= weight <= 1], [])

    def test_a_reason_never_costs_more_and_a_file_never_more_than_everywhere(self) -> None:
        for kind in (BLANKET, KEY, STYLISTIC):
            with self.subTest(kind=kind):
                for scope in (GLOBAL, FILE):
                    self.assertLessEqual(WEIGHTS[kind, scope, True], WEIGHTS[kind, scope, False])
                self.assertLessEqual(WEIGHTS[kind, FILE, False], WEIGHTS[kind, GLOBAL, False])

    def test_the_numbers_are_the_documented_ones(self) -> None:
        self.assertEqual((COVERED, DENSITY, JUSTIFIED_DENSITY, MOST_DENSITY), (0.5, 0.02, 0.005, 0.5))
        self.assertEqual(WEIGHTS[BLANKET, GLOBAL, False], 1.0)
        self.assertEqual((WEIGHTS[KEY, GLOBAL, False], WEIGHTS[KEY, FILE, True]), (0.25, 0.02))


class DiagnosticsTableTests(unittest.TestCase):
    def test_every_tool_in_the_file_turns_diagnostics_off_somewhere(self) -> None:
        tools = {disabler.tool for disabler in known_disablers()} | {"compiler"}
        self.assertEqual(sorted(set(policy_tables.load("diagnostics")) - tools), [])
        self.assertEqual(sorted(tools - set(policy_tables.load("diagnostics"))), [])

    def test_each_entry_has_only_known_fields_and_well_formed_globs(self) -> None:
        for tool, entry in policy_tables.load("diagnostics").items():
            with self.subTest(tool=tool):
                self.assertLessEqual(set(entry), {"blanket", "key", "key_of", "reasons"})
                self.assertIn(entry.get("key_of", tool), policy_tables.load("diagnostics"))
                globs = [*entry.get("key", ()), *(reason["glob"] for reason in entry.get("reasons", ()))]
                for glob in globs:
                    re.compile(translate(glob))
                    self.assertEqual(glob, glob.strip())
                self.assertEqual(len(globs), len(set(globs)), "a glob is listed twice")
                for reason in entry.get("reasons", ()):
                    self.assertEqual(set(reason), {"glob", "why"})
                    self.assertTrue(reason["why"])

    def test_a_diagnostic_with_a_reason_finds_bugs(self) -> None:
        disabler = next(found for found in known_disablers() if found.tool == "clang-tidy")
        self.assertEqual(disabler.kind("hicpp-signed-bitwise"), KEY)
        self.assertIn("sign bit", disabler.why("hicpp-signed-bitwise"))
        self.assertEqual(disabler.kind("readability-magic-numbers"), STYLISTIC)
        self.assertEqual(disabler.kind("*"), BLANKET)


class ScoreTableTests(unittest.TestCase):
    def test_the_levels_name_known_checks_once_each(self) -> None:
        checks = {check.name for check in discover().checks}
        listed = [check for level in LEVELS.values() for check in level]
        self.assertEqual(sorted(set(listed) - checks), [])
        self.assertEqual(len(listed), len(set(listed)))
        unscored = sorted((COSMETIC | FINDINGS | EXTRA_CREDIT) - checks)
        self.assertEqual(unscored, [])

    def test_every_level_has_a_name_and_the_top_is_complete(self) -> None:
        self.assertEqual(sorted(LEVEL_NAMES), list(range(TOP_LEVEL + 1)))
        self.assertEqual(sorted(LEVELS), list(range(1, TOP_LEVEL)))
        self.assertEqual(LEVEL_NAMES[TOP_LEVEL], "Complete")

    def test_the_families_group_known_tools(self) -> None:
        """A tool is named as the validator names it (`ruff check`, not `ruff`), or it is never grouped; a family is
        only a label."""
        names = {tool.name for tool in known_tools()}
        self.assertEqual(sorted(set(FAMILIES) - names), [])

    def test_the_numbers_are_the_documented_ones(self) -> None:
        self.assertEqual((EXTRA, FLOOR, SMALLEST_STEP), ((0.25, 0.10), 0.1, 0.05))
        self.assertEqual((weight_of("core"), weight_of("auxiliary"), weight_of("project")), (1.0, 0.5, 1.0))

    def test_the_docs_list_each_level_s_checks(self) -> None:
        documented = re.findall(r"^\| (\d), [A-Za-z]+ \| (.*) \|$", _DOCS.read_text(encoding="utf-8"), re.MULTILINE)
        found = {int(level): tuple(re.findall(r"`([a-z-]+)`", checks)) for level, checks in documented}
        found = {level: checks for level, checks in found.items() if checks}  # the top level lists no checks
        self.assertEqual(found, dict(LEVELS))


if __name__ == "__main__":
    unittest.main()
