"""A tool's strength (upstream #295): what its configuration turns off and the suppressions in the code weaken it, and
a gate counts in the score only when its strongest tool is at least half strong."""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from dataclasses import replace

from project_validator.core import Status
from project_validator.facts import Facts, Origin
from project_validator.facts.structure import SourceFile
from project_validator.facts.suppressions import (
    BLANKET,
    FILE,
    GLOBAL,
    KEY,
    STYLISTIC,
    Disabled,
    Suppression,
    Suppressions,
)
from project_validator.score import score
from project_validator.strength import COVERED, TurnedOff, strengths, turned_off
from tests.support import make_context, temp_project
from tests.test_score import place, report

PASS = Status.PASS


def _disabled(kind: str, scope: str = GLOBAL, *, justified: bool = False, tool: str = "clang-tidy") -> Disabled:
    return Disabled(
        origin=Origin(path=".clang-tidy"), tool=tool, diagnostic="x", kind=kind, scope=scope, justified=justified
    )


def _source(lines: int, language: str = "C++") -> SourceFile:
    return SourceFile(origin=Origin(path=f"src/{lines}.cpp"), language=language, lines=lines)


def _strength(*facts: object, tool: str = "clang-tidy") -> float:
    return strengths(Facts(facts)).get(tool, 1.0)  # type: ignore[arg-type]


def _cost(*facts: object) -> float:
    """What the facts take off clang-tidy's strength, in a project of 1,000 lines of C++."""
    return 1.0 - _strength(_source(1000), *facts)


def _inline(path: str, *found: Suppression, blanket: bool = False) -> Suppressions:
    return Suppressions(origin=Origin(path=path), tool="clang-tidy", found=found, blanket=blanket)


def _finds_bugs(rule: str = "bugprone-x", *, justified: bool = False) -> Suppression:
    return Suppression(rules=(rule,), justified=justified, kind=KEY)


def _lint(rule: str = "readability-x") -> Suppression:
    return Suppression(rules=(rule,), kind=STYLISTIC)


def _spread(count: int, *, justified: bool = False, rule: str = "bugprone-x") -> list[Suppressions]:
    """`count` comments turning off `rule`, one in each of as many files."""
    return [_inline(f"src/{number}.cpp", _finds_bugs(rule, justified=justified)) for number in range(count)]


class StrengthTests(unittest.TestCase):
    def test_what_the_configuration_turns_off_weighs_by_kind_scope_and_reason(self) -> None:
        for disabled, expected in (
            (_disabled(KEY), 0.75),
            (_disabled(KEY, justified=True), 0.88),
            (_disabled(KEY, FILE), 0.95),
            (_disabled(KEY, FILE, justified=True), 0.98),
            (_disabled(STYLISTIC), 1.0),  # style is not what strength measures
            (_disabled(STYLISTIC, justified=True), 1.0),
            (_disabled(STYLISTIC, FILE), 1.0),
            (_disabled(BLANKET), 0.0),
            (_disabled(BLANKET, FILE), 0.5),
        ):
            with self.subTest(disabled=disabled):
                self.assertAlmostEqual(_strength(disabled), expected)

    def test_weights_add_up_and_strength_is_never_below_nothing(self) -> None:
        self.assertAlmostEqual(_strength(_disabled(KEY), _disabled(KEY)), 0.5)
        self.assertEqual(_strength(*(_disabled(KEY) for _ in range(5))), 0.0)

    def test_comments_that_turn_off_rules_that_find_bugs_weigh_by_how_dense_they_are(self) -> None:
        self.assertAlmostEqual(_cost(*_spread(5)), 0.1)
        self.assertAlmostEqual(_cost(*_spread(10, justified=True)), 0.05)
        python = SourceFile(origin=Origin(path="tool.py"), language="Python", lines=9000)
        self.assertAlmostEqual(1.0 - _strength(_source(1000), python, *_spread(5)), 0.1)  # only its languages' lines

    def test_comments_that_turn_off_lint_rules_that_find_no_bugs_are_free(self) -> None:
        self.assertEqual(_cost(_inline("src/a.cpp", *(_lint() for _ in range(50)))), 0.0)
        self.assertEqual(_cost(*(_inline(f"src/{number}.cpp", _lint()) for number in range(50))), 0.0)

    def test_a_comment_naming_no_rule_turns_off_those_that_find_bugs(self) -> None:
        self.assertAlmostEqual(_cost(_inline("src/a.cpp", Suppression(kind=KEY))), 0.02)

    def test_one_comment_costs_less_than_many_and_many_less_than_turning_the_rule_off(self) -> None:
        for justified in (False, True):
            with self.subTest(justified=justified):
                one, many = _cost(*_spread(1, justified=justified)), _cost(*_spread(200, justified=justified))
                everywhere = _cost(_disabled(KEY, justified=justified))
                self.assertLess(0.0, one)
                self.assertLess(one, many)
                self.assertLess(many, everywhere)
        self.assertLess(_cost(*_spread(1, justified=True)), _cost(*_spread(1)))  # a reason costs less, never nothing

    def test_comments_in_one_file_cost_less_than_turning_the_rule_off_for_that_file(self) -> None:
        for justified in (False, True):
            with self.subTest(justified=justified):
                comments = (_finds_bugs(justified=justified) for _ in range(40))
                self.assertLess(
                    _cost(_inline("src/a.cpp", *comments)), _cost(_disabled(KEY, FILE, justified=justified))
                )

    def test_each_rule_is_held_below_turning_it_off_on_its_own(self) -> None:
        one_rule = _cost(*_spread(200))
        self.assertAlmostEqual(_cost(*_spread(200), *_spread(200, rule="bugprone-y")), 2 * one_rule)
        many_rules = [comment for rule in range(10) for comment in _spread(200, rule=f"bugprone-{rule}")]
        self.assertAlmostEqual(_cost(*many_rules), 0.5)  # the comments weigh at most half together

    def test_a_comment_naming_several_rules_counts_for_each_that_finds_bugs(self) -> None:
        both = Suppression(rules=("bugprone-x", "bugprone-y", "readability-z"), kind=KEY)
        self.assertAlmostEqual(_cost(_inline("src/a.cpp", both)), 0.04)

    def test_a_file_turned_off_whole_weighs_as_everything_off_for_one_file(self) -> None:
        self.assertAlmostEqual(_cost(_inline("src/a.cpp", blanket=True)), 0.5)

    def test_a_tool_nothing_turns_off_is_at_full_strength(self) -> None:
        self.assertNotIn("clang-tidy", strengths(Facts(())))

    def test_from_a_project(self) -> None:
        files = {"main.cpp": "int main() {}\n", ".clang-tidy": "Checks: 'bugprone-*,-bugprone-narrowing-conversions'\n"}
        with temp_project(files) as root:
            self.assertAlmostEqual(strengths(make_context(root).facts)["clang-tidy"], 0.75)


def _scored(strength: Mapping[str, float]) -> tuple[float, float, list[str]]:
    found = score([report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck"))], strengths=strength)
    return found.filled, found.extra_slots, [step.check for step in found.next_steps]


class ScoreTests(unittest.TestCase):
    def test_a_gate_counts_only_when_its_strongest_tool_is_half_strong(self) -> None:
        self.assertEqual(COVERED, 0.5)
        self.assertEqual(_scored({"clang-tidy": 0.4, "cppcheck": 0.3})[:1], (0,))
        self.assertEqual(_scored({"clang-tidy": 0.4, "cppcheck": 0.3})[2], ["static-analysis"])
        self.assertEqual(_scored({})[0], 1)

    def test_a_slot_is_filled_as_far_as_its_strongest_tool_is_strong(self) -> None:
        """Every cost shows in the score: a tool at 0.9 fills 0.9 of its slot, not all of it."""
        self.assertAlmostEqual(_scored({"clang-tidy": 0.4, "cppcheck": 0.6})[0], 0.6)
        self.assertAlmostEqual(_scored({"clang-tidy": 0.99})[0], 1.0)  # cppcheck is still at full strength
        self.assertAlmostEqual(_scored({"clang-tidy": 0.9, "cppcheck": 0.75})[0], 0.9)
        self.assertEqual(_scored({"clang-tidy": 0.9, "cppcheck": 0.75})[2], [])  # still in place: not a next step

    def test_extra_credit_scales_with_the_tools_strength(self) -> None:
        full, half = _scored({})[1], _scored({"clang-tidy": 0.5, "cppcheck": 0.5})[1]
        self.assertAlmostEqual(half, full * 0.5)  # by their mean strength, once: not again by the slot's fill

    def test_the_cell_says_how_strong_its_tools_are(self) -> None:
        found = score([report("static-analysis", PASS, place(PASS, "clang-tidy"))], strengths={"clang-tidy": 0.75})
        self.assertEqual(found.as_dict()["cells"][0]["strength"], 0.75)  # type: ignore[index]

    def test_a_place_with_no_tools_is_as_strong_as_it_is(self) -> None:
        found = score([report("license", PASS)], strengths={"clang-tidy": 0.0})
        self.assertEqual(found.filled, 1)


if __name__ == "__main__":
    unittest.main()


class ReenableTests(unittest.TestCase):
    """The best next step the score can give: turn back on a diagnostic that finds bugs, and fix what it finds."""

    def test_turned_off_lists_what_finds_bugs_heaviest_first(self) -> None:
        facts = Facts(
            (
                _disabled(STYLISTIC),
                Disabled(origin=Origin(path=".clang-tidy"), tool="clang-tidy", diagnostic="bugprone-a", kind=KEY),
                Disabled(origin=Origin(path="CMakeLists.txt"), tool="clang-tidy", diagnostic="*", kind=BLANKET),
            )
        )
        self.assertEqual(
            [(found.diagnostic, found.path, found.weight) for found in turned_off(facts)],
            [("*", "CMakeLists.txt", 1.0), ("bugprone-a", ".clang-tidy", 0.25)],
        )

    def test_re_enabling_a_diagnostic_is_a_step_worth_what_it_restores(self) -> None:
        off = TurnedOff(tool="clang-tidy", diagnostic="bugprone-a", path=".clang-tidy", weight=0.25)
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy")), report("tests-run", PASS, place(PASS))]
        blocked = score(reports, strengths={"clang-tidy": 0.4}, turned_off=(off,))
        [step] = [step for step in blocked.next_steps if step.message.startswith("re-enable")]
        self.assertEqual(step.message, "re-enable bugprone-a in .clang-tidy (clang-tidy)")
        self.assertEqual(step.hint, "re-enable bugprone-a in .clang-tidy and fix what clang-tidy finds")
        self.assertEqual(
            step.describe(),
            "static-analysis (C++): +32.5 points; re-enable bugprone-a in .clang-tidy and fix what clang-tidy finds",
        )
        self.assertAlmostEqual(step.points, 32.5)  # the slot fills again, to 0.65 of it: of two slots, 32.5 points
        unblocked = score(reports, strengths={"clang-tidy": 0.75}, turned_off=(off,))
        [step] = [step for step in unblocked.next_steps if step.message.startswith("re-enable")]
        self.assertAlmostEqual(step.points, 12.5)  # a gate in place still gains what turning it back on restores

    def test_a_step_says_why_its_diagnostic_matters_where_it_is_known(self) -> None:
        why = "it guards against undefined behaviour: reads and writes out of bounds"
        off = TurnedOff(tool="clang-tidy", diagnostic="cppcoreguidelines-pro-bounds-x", path=".clang-tidy", weight=0.25)
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy"))]
        found = score(reports, strengths={"clang-tidy": 0.4}, turned_off=(replace(off, why=why),))
        [step] = [step for step in found.next_steps if step.message.startswith("re-enable")]
        self.assertEqual(
            step.hint,
            f"re-enable cppcoreguidelines-pro-bounds-x in .clang-tidy and fix what clang-tidy finds; {why}",
        )

    def test_turned_off_carries_why_its_diagnostic_matters(self) -> None:
        disabled = Disabled(
            origin=Origin(path=".clang-tidy"), tool="clang-tidy", diagnostic="hicpp-a", kind=KEY, why="it guards"
        )
        self.assertEqual([found.why for found in turned_off(Facts((disabled,)))], ["it guards"])

    def test_a_gain_too_small_to_show_is_no_step(self) -> None:
        """Extra credit restored by a hair: not worth a tenth of a point, so not a step (the board shows tenths)."""
        off = TurnedOff(tool="clang-tidy", diagnostic="bugprone-a", path=".clang-tidy", weight=0.001)
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck"))]
        found = score(reports, strengths={"clang-tidy": 0.6}, turned_off=(off,))
        self.assertFalse([step for step in found.next_steps if step.message.startswith("re-enable")])

    def test_it_restores_its_own_tool_alone(self) -> None:
        off = TurnedOff(tool="clang-tidy", diagnostic="bugprone-a", path=".clang-tidy", weight=0.15)
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck"))]
        found = score(reports, strengths={"clang-tidy": 0.3, "cppcheck": 0.4}, turned_off=(off,))
        self.assertFalse([step for step in found.next_steps if step.message.startswith("re-enable")])  # 0.45: not yet

    def test_from_a_project(self) -> None:
        files = {"main.cpp": "int main() {}\n", ".clang-tidy": "Checks: 'bugprone-*,-bugprone-narrowing-conversions'\n"}
        with temp_project(files) as root:
            [found] = turned_off(make_context(root).facts)
        self.assertEqual(
            (found.tool, found.diagnostic, found.path), ("clang-tidy", "bugprone-narrowing-conversions", ".clang-tidy")
        )
