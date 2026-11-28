"""Where a score loses its points (upstream #295): each slot's shortfall, split by cause, so the report says what to
correct and not only what would add points."""

from __future__ import annotations

import json
import unittest
from typing import ClassVar

from project_validator.analysis import Analysis
from project_validator.core import Placed, Result, Status
from project_validator.losses import CAUSES, in_points, losses
from project_validator.score import Score, score
from tests.support import requires_rich
from tests.test_score import place, report

PASS, WARN, FAIL, ERROR = Status.PASS, Status.WARN, Status.FAIL, Status.ERROR


def _by_cause(scored: Score) -> dict[str, float]:
    return {found.cause: round(found.points, 6) for found in losses(scored)}


class LossesTests(unittest.TestCase):
    def test_each_status_loses_to_its_own_cause(self) -> None:
        scored = score(
            [
                report("code-formatting", PASS, place(PASS, "clang-format")),
                report("static-analysis", FAIL, place(FAIL)),
                report("coverage", ERROR, place(ERROR)),
                report("tests-run", WARN, place(WARN, "ctest")),
            ]
        )
        self.assertEqual(_by_cause(scored), {"failing": 25.0, "unknown": 25.0, "warning": 12.5})

    def test_the_causes_add_up_to_what_the_score_lacks(self) -> None:
        partial = Placed(ecosystem="C++", unit=".", result=Result(status=PASS, message="", share=0.5), tools=("gcovr",))
        scored = score(
            [
                report("static-analysis", PASS, place(PASS, "clang-tidy")),
                report("coverage", PASS, partial),
                report("tests-run", FAIL, place(FAIL)),
            ],
            strengths={"clang-tidy": 0.8},
        )
        self.assertAlmostEqual(sum(found.points for found in losses(scored)), 100.0 - scored.base)
        self.assertEqual(_by_cause(scored), {"failing": 33.333333, "reach": 16.666667, "turned-off": 6.666667})

    def test_a_tool_turned_off_below_half_loses_its_whole_slot_to_what_is_turned_off(self) -> None:
        scored = score([report("static-analysis", PASS, place(PASS, "clang-tidy"))], strengths={"clang-tidy": 0.4})
        self.assertEqual(_by_cause(scored), {"turned-off": 100.0})

    def test_what_weakens_a_tool_is_split_between_its_configuration_and_the_comments(self) -> None:
        scored = score(
            [report("static-analysis", PASS, place(PASS, "clang-tidy"))],
            strengths={"clang-tidy": 0.7},
            weakened={"clang-tidy": (0.25, 0.05)},
        )
        [found] = losses(scored)
        [slot] = found.slots
        self.assertEqual(
            slot.detail, "clang-tidy at 0.7: 0.25 turned off in its configuration, 0.05 by comments in the code"
        )

    def test_small_losses_and_costs_are_not_rounded_away(self) -> None:
        scored = score(
            [report("static-analysis", PASS, place(PASS, "ruff check"))],
            strengths={"ruff check": 0.9975},
            weakened={"ruff check": (0.0, 0.0025)},
        )
        [found] = losses(scored)
        self.assertEqual(
            found.slots[0].describe(),
            "static-analysis (C++): 0.25 points; ruff check at 0.998: 0 turned off in its configuration, "
            "0.0025 by comments in the code",
        )
        self.assertEqual([in_points(value) for value in (12.4, 3.25, 0.25, 0.004)], ["12", "3.2", "0.25", "<0.01"])

    def test_a_defect_the_validator_found_is_its_own_cause(self) -> None:
        scored = score([report("large-files", FAIL, place(FAIL, ecosystem=""))])
        self.assertEqual(_by_cause(scored), {"found": 100.0})

    def test_causes_and_their_slots_come_heaviest_first(self) -> None:
        scored = score(
            [
                report("static-analysis", FAIL, place(FAIL), place(FAIL, ecosystem="Python")),
                report("coverage", ERROR, place(ERROR)),
            ],
            sizes={("C++", "."): 0.9, ("Python", "."): 0.1},
        )
        found = losses(scored)
        self.assertEqual([each.cause for each in found], ["failing", "unknown"])
        self.assertEqual([slot.where for slot in found[0].slots], ["C++", "Python"])

    def test_a_full_score_loses_nothing(self) -> None:
        self.assertEqual(losses(score([report("license", PASS, place(PASS, ecosystem=""))])), ())

    def test_every_cause_says_what_to_correct(self) -> None:
        self.assertEqual(set(CAUSES), {"failing", "unknown", "warning", "reach", "turned-off", "found"})
        for cause, (title, correct) in CAUSES.items():
            with self.subTest(cause=cause):
                self.assertTrue(title and correct)

    def test_the_json_lists_the_losses(self) -> None:
        data = json.loads(json.dumps(score([report("static-analysis", FAIL, place(FAIL))]).as_dict()))
        [lost] = data["losses"]
        self.assertEqual((lost["cause"], lost["points"]), ("failing", 100.0))
        self.assertEqual(lost["slots"][0]["check"], "static-analysis")


if __name__ == "__main__":
    unittest.main()


class LossViewTests(unittest.TestCase):
    """Every view says where the points are lost, before what would add them."""

    analysis: ClassVar[Analysis]

    @classmethod
    def setUpClass(cls) -> None:
        from tests.test_views import _analysis

        cls.analysis = _analysis()

    def test_the_text_report_lists_each_cause_with_its_heaviest_slots(self) -> None:
        from project_validator.views import text

        report = text.render(self.analysis, scored=True)
        self.assertIn("Where points are lost:", report)
        self.assertLess(report.index("Where points are lost:"), report.index("Next steps:"))
        self.assertRegex(report, r"\n  - Gates that fail: [\d.]+ points in \d+ slots?; put the gate in place")
        self.assertRegex(report, r"\n      - [\w-]+( \([^)]*\))?: [\d.]+ points")

    def test_the_tui_has_a_page_for_it(self) -> None:
        from project_validator.views import tui

        self.assertIn("Gates that fail", tui.losses_page(self.analysis))

    def test_the_html_report_has_a_section_for_it(self) -> None:
        from project_validator.views import html

        page = html.render(self.analysis)
        self.assertIn('id="lost"', page)
        self.assertIn("Gates that fail", page)
        self.assertLess(page.index('id="lost"'), page.index('id="next"'))

    @requires_rich
    def test_the_console_report_lists_it(self) -> None:
        import io

        from project_validator.views import console

        stream = io.StringIO()
        console.render(self.analysis, stream, width=200)
        output = stream.getvalue()
        self.assertIn("Where points are lost", output)
        self.assertLess(output.index("Where points are lost"), output.index("Next steps"))


class LeaderboardLossTests(unittest.TestCase):
    """The leaderboard's pages and its preview comment say where a project loses points; a night recorded before
    there were losses in the score still renders."""

    SCORED: ClassVar[dict[str, object]] = score([report("static-analysis", FAIL, place(FAIL))]).as_dict()

    def test_a_project_page_lists_the_losses(self) -> None:
        from leaderboard import site

        self.assertIn("Gates that fail", site.losses_card(self.SCORED))
        self.assertEqual(site.losses_card({"percent": 100}), "")

    def test_the_preview_says_where_points_are_lost(self) -> None:
        from leaderboard.__main__ import loss_lines

        self.assertEqual(
            loss_lines(self.SCORED),
            ["Where points are lost:", "", "- Gates that fail: 100 points (`static-analysis` (C++))", ""],
        )
        self.assertEqual(loss_lines({"percent": 100}), [])
