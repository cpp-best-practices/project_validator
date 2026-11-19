"""The tooling score, version 1 (upstream #295): 100% means every quality gate that applies to each part of the
project is in place, and extra credit above 100% rewards complementary tools, once every gate is. Statuses and exit
codes do not change; the score is read from the reports alone."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, main
from project_validator.core import Check, Placed, Result, Status
from project_validator.runner import Report
from project_validator.score import (
    LEVEL_NAMES,
    LEVELS,
    NOT_FOR_AUXILIARY,
    SCORE_VERSION,
    UNSCORED,
    Score,
    family,
    score,
)
from tests.support import FIXTURES

PASS, WARN, FAIL, ERROR, SKIP = Status.PASS, Status.WARN, Status.FAIL, Status.ERROR, Status.SKIP


def _check(name: str) -> Check:
    return Check(name=name, description=f"what {name} asks", run=lambda _: Result.passed(""))


def place(
    status: Status,
    *tools: str,
    ecosystem: str = "C++",
    unit: str = ".",
    auxiliary: tuple[str, ...] = (),
    message: str = "",
    details: tuple[str, ...] = (),
) -> Placed:
    return Placed(
        ecosystem=ecosystem,
        unit=unit,
        result=Result(status=status, message=message, details=details),
        tools=tools,
        auxiliary=auxiliary,
    )


def report(name: str, status: Status, *places: Placed) -> Report:
    return Report(check=_check(name), result=Result(status=status, message=f"{name} {status}", places=places))


def project_wide(name: str, status: Status, message: str = "") -> Report:
    return Report(check=_check(name), result=Result(status=status, message=message or f"{name} {status}"))


def foundations(status: Status = PASS) -> list[Report]:
    """Every level 1 check, each with one core place (or project-wide, for checks of every project)."""
    return [
        project_wide(name, status) if name in ("ci-present", "license") else report(name, status, place(status))
        for name in LEVELS[1]
    ]


def scored(*reports: Report | list[Report], every_check: tuple[str, ...] = ()) -> Score:
    flat: list[Report] = []
    for item in reports:
        flat.extend(item if isinstance(item, list) else [item])
    return score(flat, every_check)


class PercentTests(unittest.TestCase):
    """Base: the share of the applicable slots that are filled, pooled across the project."""

    def test_every_gate_in_place_is_100_percent(self) -> None:
        self.assertEqual(scored(foundations()).percent, 100)

    def test_a_missing_gate_costs_its_share_of_the_slots(self) -> None:
        reports = [report("tests-run", PASS, place(PASS)), report("coverage", FAIL, place(FAIL))]
        self.assertEqual(scored(reports).percent, 50)

    def test_a_warning_fills_half_a_slot(self) -> None:
        reports = [report("tests-run", PASS, place(PASS)), report("coverage", WARN, place(WARN))]
        self.assertEqual(scored(reports).percent, 75)

    def test_an_error_stays_in_the_slots_and_fills_nothing(self) -> None:
        reports = [report("tests-run", PASS, place(PASS)), report("coverage", ERROR, place(ERROR))]
        self.assertEqual(scored(reports).percent, 50)

    def test_a_skip_is_not_a_slot(self) -> None:
        reports = [report("tests-run", PASS, place(PASS)), report("coverage", SKIP, place(SKIP))]
        self.assertEqual(scored(reports).percent, 100)

    def test_slots_are_pooled_so_a_small_part_weighs_its_size(self) -> None:
        """A one-gate data folder weighs one slot, not as much as the code with three."""
        reports = [
            report("tests-run", PASS, place(PASS), place(FAIL, ecosystem="Data")),
            report("coverage", PASS, place(PASS)),
            report("static-analysis", PASS, place(PASS)),
        ]
        self.assertEqual(scored(reports).percent, 75)

    def test_auxiliary_slots_weigh_half(self) -> None:
        reports = [report("static-analysis", FAIL, place(PASS), place(FAIL, ecosystem="Python", auxiliary=("test",)))]
        self.assertAlmostEqual(scored(reports).percent, 100 * 1 / 1.5)

    def test_auxiliary_code_is_not_asked_for_the_product_only_gates(self) -> None:
        for check in sorted(NOT_FOR_AUXILIARY):
            with self.subTest(check=check):
                reports = [report(check, FAIL, place(PASS), place(FAIL, ecosystem="Python", auxiliary=("test",)))]
                self.assertEqual(scored(reports).percent, 100)

    def test_unscored_checks_are_reported_not_scored(self) -> None:
        self.assertIn("status-badges", UNSCORED)
        reports = [report("tests-run", PASS, place(PASS)), project_wide("status-badges", WARN)]
        self.assertEqual(scored(reports).percent, 100)

    def test_project_wide_checks_are_one_slot_each(self) -> None:
        reports = [report("tests-run", PASS, place(PASS)), project_wide("license", FAIL)]
        result = scored(reports)
        self.assertEqual((result.filled, result.slots), (1, 2))

    def test_nothing_to_score_is_100_percent(self) -> None:
        self.assertEqual(scored([]).percent, 100)


class ExtraCreditTests(unittest.TestCase):
    """Complementary tools earn extra credit, held until every gate is in place."""

    def test_a_second_distinct_tool_earns_a_quarter_slot(self) -> None:
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck"))]
        self.assertEqual(scored(reports).percent, 125)

    def test_a_third_earns_a_tenth_and_more_earn_nothing(self) -> None:
        reports = [report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck", "PVS-Studio", "Infer"))]
        self.assertEqual(scored(reports).percent, 135)

    def test_extra_credit_is_held_until_every_gate_is_in_place(self) -> None:
        reports = [
            report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck")),
            report("coverage", FAIL, place(FAIL)),
        ]
        result = scored(reports)
        self.assertEqual(result.percent, 50)
        self.assertEqual(result.held, 12.5)

    def test_only_complementary_gates_earn_extra_credit(self) -> None:
        """Two formatters, or two coverage tools, do not make a project stronger."""
        for check in ("code-formatting", "coverage", "mutation-testing", "tests-run"):
            with self.subTest(check=check):
                self.assertEqual(scored([report(check, PASS, place(PASS, "one", "two"))]).percent, 100)

    def test_tools_of_one_family_count_once(self) -> None:
        reports = [report("static-analysis", PASS, place(PASS, "ruff", "flake8"))]
        self.assertEqual(scored(reports).percent, 100)
        reports = [report("security-scanning", PASS, place(PASS, "golangci-lint's gosec", "golangci-lint's revive"))]
        self.assertEqual(scored(reports).percent, 100)

    def test_a_bundled_linter_belongs_to_its_bundle(self) -> None:
        self.assertEqual(family("golangci-lint's gosec"), "golangci-lint")
        self.assertEqual(family("flake8"), family("ruff"))
        self.assertEqual(family("CodeQL"), "CodeQL")

    def test_extra_credit_scales_with_the_slot(self) -> None:
        reports = [
            report(
                "static-analysis",
                PASS,
                place(PASS, "clang-tidy"),
                place(PASS, "ruff", "mypy", ecosystem="Python", auxiliary=("test",)),
            )
        ]
        self.assertAlmostEqual(scored(reports).percent, 100 + 100 * 0.25 * 0.5 / 1.5)


class LevelTests(unittest.TestCase):
    def test_a_project_missing_a_foundation_is_level_0(self) -> None:
        reports = foundations()
        reports[0] = report(reports[0].check.name, FAIL, place(FAIL))
        self.assertEqual(scored(reports).level, 0)

    def test_every_foundation_passing_in_core_code_is_level_1(self) -> None:
        self.assertEqual(scored(foundations()).level, 1)

    def test_a_warning_does_not_complete_a_level(self) -> None:
        reports = foundations()
        reports[-1] = report(reports[-1].check.name, WARN, place(WARN))
        self.assertEqual(scored(reports).level, 0)

    def test_auxiliary_code_does_not_hold_a_level_back(self) -> None:
        reports = foundations()
        reports[-1] = report(
            reports[-1].check.name, FAIL, place(PASS), place(FAIL, ecosystem="Python", auxiliary=("scripts",))
        )
        self.assertEqual(scored(reports).level, 1)

    def test_levels_are_gated_in_order(self) -> None:
        analysis = [report(name, PASS, place(PASS, "tool")) for name in LEVELS[2]]
        hardening = [report(name, PASS, place(PASS, "tool")) for name in LEVELS[3]]
        self.assertEqual(scored(analysis).level, 0)
        self.assertEqual(scored(foundations(), analysis).level, 2)
        self.assertEqual(scored(foundations(), analysis, hardening, every_check=("security-policy",)).level, 3)

    def test_the_top_level_is_100_percent_with_every_check_run(self) -> None:
        analysis = [report(name, PASS, place(PASS, "tool")) for name in LEVELS[2]]
        hardening = [report(name, PASS, place(PASS, "tool")) for name in LEVELS[3]]
        every = (*(name for level in LEVELS.values() for name in level), "secret-scanning")
        complete = project_wide("secret-scanning", PASS)
        self.assertEqual(scored(foundations(), analysis, hardening, complete, every_check=every).level, 4)
        incomplete = project_wide("secret-scanning", WARN)
        self.assertEqual(scored(foundations(), analysis, hardening, incomplete, every_check=every).level, 3)

    def test_a_level_needs_its_checks_to_have_run(self) -> None:
        self.assertEqual(scored(foundations()[1:]).level, 0)

    def test_every_level_has_a_name(self) -> None:
        self.assertEqual(set(LEVEL_NAMES), {0, 1, 2, 3, 4})
        self.assertEqual(LEVEL_NAMES[4], "Complete")


class NextStepTests(unittest.TestCase):
    def test_each_unfilled_slot_is_a_next_step_worth_its_points(self) -> None:
        reports = [
            report("tests-run", PASS, place(PASS)),
            report("coverage", FAIL, place(FAIL, message="no coverage", details=("run gcovr in CI",))),
            report("fuzz-testing", WARN, place(WARN)),
        ]
        steps = {step.check: step for step in scored(reports).next_steps}
        self.assertEqual(set(steps), {"coverage", "fuzz-testing"})
        self.assertAlmostEqual(steps["coverage"].points, 100 / 3)
        self.assertAlmostEqual(steps["fuzz-testing"].points, 100 / 6)
        self.assertEqual(steps["coverage"].message, "no coverage")
        self.assertEqual(steps["coverage"].hint, "run gcovr in CI")

    def test_the_next_levels_blockers_come_first(self) -> None:
        reports = [*foundations(), report("fuzz-testing", FAIL, place(FAIL))]
        reports[0] = report(reports[0].check.name, FAIL, place(FAIL))
        first = scored(reports).next_steps[0]
        self.assertEqual((first.check, first.needed_for), (reports[0].check.name, 1))

    def test_a_next_step_says_what_to_do_where_and_what_it_is_worth(self) -> None:
        reports = [
            report("tests-run", PASS, place(PASS)),
            report("coverage", FAIL, place(FAIL, unit="lib", details=("run gcovr in CI",))),
        ]
        (step,) = scored(reports).next_steps
        self.assertEqual(step.describe(), "coverage (C++ in lib): +50 points; run gcovr in CI")

    def test_a_project_wide_step_names_no_place(self) -> None:
        (step,) = scored([report("tests-run", PASS, place(PASS)), project_wide("license", FAIL)]).next_steps
        self.assertTrue(step.describe().startswith("license: +50 points"))

    def test_the_step_that_completes_a_level_says_so(self) -> None:
        reports = foundations()
        reports[0] = report(reports[0].check.name, FAIL, place(FAIL))
        (step,) = scored(reports).next_steps
        self.assertIn("completes Level 1 (Foundations)", step.describe())


class SummaryTests(unittest.TestCase):
    def test_the_summary_is_the_percent_the_level_and_the_gates(self) -> None:
        reports = [*foundations(), report("coverage", FAIL, place(FAIL))]
        self.assertEqual(scored(reports).summary(), "87% · Level 1 Foundations · 7 of 8 gates in place")

    def test_past_100_the_summary_shows_the_extra_credit(self) -> None:
        reports = [*foundations(), report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck"))]
        expected = "103% · Level 1 Foundations · all 8 gates in place, +3 extra credit"
        self.assertEqual(scored(reports).summary(), expected)

    def test_held_extra_credit_is_mentioned(self) -> None:
        reports = [
            report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck")),
            report("coverage", FAIL, place(FAIL)),
        ]
        self.assertIn("+12 extra credit held until every gate is in place", scored(reports).summary())

    def test_the_breakdown_is_by_language(self) -> None:
        reports = [
            report("tests-run", PASS, place(PASS), place(FAIL, ecosystem="Python")),
            project_wide("license", PASS),
        ]
        self.assertEqual(scored(reports).breakdown(), {"C++": (1, 1), "Python": (0, 1), "": (1, 1)})

    def test_as_json(self) -> None:
        data = scored(foundations()).as_dict()
        self.assertEqual(data["version"], SCORE_VERSION)
        self.assertEqual(SCORE_VERSION, "1")
        self.assertEqual(data["percent"], 100)
        self.assertEqual((data["level"], data["level_name"]), (1, "Foundations"))
        self.assertEqual((data["filled"], data["slots"], data["extra"], data["held"]), (7, 7, 0, 0))
        self.assertEqual(len(data["cells"]), 7)
        json.dumps(data)


class CliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main([*arguments])
        return code, output.getvalue()

    def test_the_score_is_appended_to_the_text_report(self) -> None:
        code, output = self._run("--score", "--color", "never", str(FIXTURES / "well_configured_python"))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertRegex(output, r"Score: 1\d\d% · Level 4 Complete · all \d+ gates in place")

    def test_json_holds_the_results_and_the_score(self) -> None:
        code, output = self._run("--score", "--format", "json", str(FIXTURES / "bare_python"))
        self.assertEqual(code, EXIT_FAILURE)
        data = json.loads(output)
        self.assertEqual(set(data), {"results", "score"})
        self.assertLess(data["score"]["percent"], 100)

    def test_the_next_steps_are_listed(self) -> None:
        _, output = self._run("--score", "--color", "never", str(FIXTURES / "bare_python"))
        self.assertIn("Next steps:", output)


if __name__ == "__main__":
    unittest.main()
