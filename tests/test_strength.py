"""A tool's strength (upstream #295): what its configuration turns off and the suppressions in the code weaken it, and
a gate counts in the score only when its strongest tool is at least half strong."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.core import Status
from project_validator.facts import Facts, Origin
from project_validator.facts.structure import SourceFile
from project_validator.facts.suppressions import BLANKET, FILE, GLOBAL, KEY, STYLISTIC, Disabled, Suppressions
from project_validator.score import score
from project_validator.strength import COVERED, strengths
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


class StrengthTests(unittest.TestCase):
    def test_what_the_configuration_turns_off_weighs_by_kind_scope_and_reason(self) -> None:
        for disabled, expected in (
            (_disabled(KEY), 0.75),
            (_disabled(KEY, justified=True), 0.88),
            (_disabled(KEY, FILE), 0.95),
            (_disabled(KEY, FILE, justified=True), 0.98),
            (_disabled(STYLISTIC), 0.98),
            (_disabled(STYLISTIC, FILE), 1.0),
            (_disabled(BLANKET), 0.0),
            (_disabled(BLANKET, FILE), 0.5),
        ):
            with self.subTest(disabled=disabled):
                self.assertAlmostEqual(_strength(disabled), expected)

    def test_weights_add_up_and_strength_is_never_below_nothing(self) -> None:
        self.assertAlmostEqual(_strength(_disabled(KEY), _disabled(KEY)), 0.5)
        self.assertEqual(_strength(*(_disabled(KEY) for _ in range(5))), 0.0)

    def test_suppressions_in_the_code_weigh_by_how_dense_they_are(self) -> None:
        unjustified = Suppressions(origin=Origin(path="src/a.cpp"), tool="clang-tidy", count=10)
        self.assertAlmostEqual(_strength(_source(1000), unjustified), 0.8)
        justified = Suppressions(origin=Origin(path="src/a.cpp"), tool="clang-tidy", count=10, justified=10)
        self.assertAlmostEqual(_strength(_source(1000), justified), 0.95)
        many = Suppressions(origin=Origin(path="src/a.cpp"), tool="clang-tidy", count=500)
        self.assertAlmostEqual(_strength(_source(1000), many), 0.5)  # density weighs at most half
        python = SourceFile(origin=Origin(path="tool.py"), language="Python", lines=9000)
        self.assertAlmostEqual(_strength(_source(1000), python, unjustified), 0.8)  # only its languages' lines count
        whole = Suppressions(origin=Origin(path="src/a.cpp"), tool="clang-tidy", count=0, blanket=True)
        self.assertAlmostEqual(_strength(_source(1000), whole), 0.5)  # a file turned off whole

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
        self.assertEqual(_scored({"clang-tidy": 0.4, "cppcheck": 0.6})[0], 1)
        self.assertEqual(_scored({})[0], 1)

    def test_extra_credit_scales_with_the_tools_strength(self) -> None:
        full, half = _scored({})[1], _scored({"clang-tidy": 0.5, "cppcheck": 0.5})[1]
        self.assertAlmostEqual(half, full * 0.5)

    def test_the_cell_says_how_strong_its_tools_are(self) -> None:
        found = score([report("static-analysis", PASS, place(PASS, "clang-tidy"))], strengths={"clang-tidy": 0.75})
        self.assertEqual(found.as_dict()["cells"][0]["strength"], 0.75)  # type: ignore[index]

    def test_a_place_with_no_tools_is_as_strong_as_it_is(self) -> None:
        found = score([report("license", PASS)], strengths={"clang-tidy": 0.0})
        self.assertEqual(found.filled, 1)


if __name__ == "__main__":
    unittest.main()
