"""The tooling score (upstream #295): breadth before depth, core code before auxiliary, foundations before flashy
tools. Statuses and exit codes do not change; the score is read from the reports alone."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, main
from project_validator.core import Check, Placed, Result, Status
from project_validator.runner import Report
from project_validator.score import LEVELS, SCORE_VERSION, Score, score
from tests.support import FIXTURES

PASS, WARN, FAIL, ERROR, SKIP = Status.PASS, Status.WARN, Status.FAIL, Status.ERROR, Status.SKIP


def _check(name: str) -> Check:
    return Check(name=name, description=name, run=lambda _: Result.passed(""))


def place(
    status: Status, *tools: str, ecosystem: str = "C/C++", unit: str = ".", auxiliary: tuple[str, ...] = ()
) -> Placed:
    return Placed(
        ecosystem=ecosystem, unit=unit, result=Result(status=status, message=""), tools=tools, auxiliary=auxiliary
    )


def report(name: str, status: Status, *places: Placed) -> Report:
    return Report(check=_check(name), result=Result(status=status, message=f"{name} {status}", places=places))


def project_wide(name: str, status: Status) -> Report:
    return report(name, status)


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
        self.assertEqual(scored(foundations(), analysis).level, 2)
        self.assertEqual(scored(foundations(), analysis, hardening, every_check=("security-policy",)).level, 3)
        broken = foundations()
        broken[0] = report(broken[0].check.name, FAIL, place(FAIL))
        self.assertEqual(scored(broken, analysis, hardening).level, 0)

    def test_a_level_whose_checks_all_skip_is_complete(self) -> None:
        analysis = [report(name, SKIP) for name in LEVELS[2]]
        self.assertEqual(scored(foundations(), analysis).level, 2)

    def test_level_4_needs_every_applicable_cell_in_every_tier(self) -> None:
        every: list[Report | list[Report]] = [
            foundations(),
            [report(name, PASS, place(PASS, "tool")) for name in (*LEVELS[2], *LEVELS[3])],
            project_wide("security-policy", PASS),
        ]
        self.assertEqual(scored(*every, every_check=("security-policy",)).level, 4)
        helper = report("status-badges", FAIL, place(FAIL, ecosystem="Python", auxiliary=("scripts",)))
        self.assertEqual(scored(*every, helper).level, 3)
        self.assertEqual(scored(*every, every_check=("security-policy", "large-files")).level, 3)


class NarrowedRunTests(unittest.TestCase):
    def test_a_level_whose_checks_did_not_run_is_not_reached(self) -> None:
        self.assertEqual(scored(foundations()[1:]).level, 0)
        self.assertEqual(scored(foundations(), report("coverage", PASS, place(PASS))).level, 1)


class CompletenessTests(unittest.TestCase):
    def test_passing_cells_over_applicable_cells(self) -> None:
        reports = [report("static-analysis", FAIL, place(PASS), place(FAIL, ecosystem="Python")), report("x", SKIP)]
        self.assertEqual(scored(reports).completeness, 0.5)

    def test_a_warning_covers_half_a_cell(self) -> None:
        self.assertEqual(scored(report("coverage", WARN, place(WARN))).completeness, 0.5)

    def test_an_error_or_unknown_scores_0_but_stays_in_the_maximum(self) -> None:
        self.assertEqual(
            scored(report("tests-run", ERROR, place(PASS), place(ERROR, ecosystem="Go"))).completeness, 0.5
        )

    def test_auxiliary_cells_weigh_half(self) -> None:
        reports = report("static-analysis", FAIL, place(PASS), place(FAIL, ecosystem="Python", auxiliary=("scripts",)))
        self.assertAlmostEqual(scored(reports).completeness, 1 / 1.5)

    def test_an_untooled_language_lowers_completeness(self) -> None:
        tooled = scored(report("static-analysis", PASS, place(PASS)))
        untooled = scored(report("static-analysis", FAIL, place(PASS), place(FAIL, ecosystem="Shell")))
        self.assertLess(untooled.completeness, tooled.completeness)

    def test_completeness_is_averaged_across_units(self) -> None:
        reports = [
            report("static-analysis", FAIL, place(PASS), place(FAIL, unit="a"), place(FAIL, unit="a", ecosystem="Go")),
            project_wide("license", PASS),
        ]
        # unit ".": 1/1, unit "a": 0/2, the project: 1/1
        self.assertAlmostEqual(scored(reports).completeness, 2 / 3)

    def test_nothing_applicable_is_complete(self) -> None:
        self.assertEqual(scored(report("fuzz-testing", SKIP)).completeness, 1.0)


class DepthTests(unittest.TestCase):
    def test_breadth_beats_depth(self) -> None:
        one_each = scored(foundations(), report("static-analysis", PASS, place(PASS, "clang-tidy")))
        both_in_one = scored(foundations(), report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck")))
        self.assertEqual(one_each.depth, both_in_one.depth - 5)
        self.assertGreater(
            scored(
                foundations(),
                report("static-analysis", PASS, place(PASS, "clang-tidy")),
                report("coverage", PASS, place(PASS, "gcovr")),
            ).depth,
            both_in_one.depth,
        )

    def test_each_tool_in_a_cell_earns_less_than_the_one_before(self) -> None:
        base = scored(foundations()).depth
        points = [
            scored(foundations(), report("static-analysis", PASS, place(PASS, *tools))).depth - base
            for tools in (("a",), ("a", "b"), ("a", "b", "c"), ("a", "b", "c", "d"), tuple("abcdefgh"))
        ]
        self.assertEqual(points, [10, 15, 17, 18, 20])

    def test_core_beats_auxiliary(self) -> None:
        base = scored(foundations()).depth
        auxiliary = report("static-analysis", PASS, place(PASS, "ruff", "mypy", "x", "y", auxiliary=("scripts",)))
        self.assertEqual(scored(foundations(), auxiliary).depth - base, 5 + 2 + 1)

    def test_a_covered_cell_earns_its_first_rank_without_a_named_tool(self) -> None:
        base = scored(foundations()).depth
        self.assertEqual(scored(foundations(), report("coverage", PASS, place(PASS))).depth - base, 10)

    def test_a_project_wide_pass_earns_a_flat_5(self) -> None:
        self.assertEqual(scored(project_wide("security-policy", PASS)).locked_depth, 5)

    def test_a_warning_earns_half_and_a_failure_nothing(self) -> None:
        base = scored(foundations()).depth
        self.assertEqual(scored(foundations(), report("coverage", WARN, place(WARN, "gcovr"))).depth - base, 5)
        self.assertEqual(scored(foundations(), report("coverage", FAIL, place(FAIL, "gcovr"))).depth - base, 0)

    def test_depth_counts_only_once_the_levels_below_are_complete(self) -> None:
        hardening = report("sanitizers", PASS, place(PASS, "ASan", "UBSan"))
        result = scored(foundations(), report("static-analysis", FAIL, place(FAIL)), hardening)
        self.assertEqual(result.level, 1)
        self.assertEqual(result.locked_depth, 15)
        self.assertNotIn("sanitizers", [cell.check for cell in result.cells if cell.counted])

    def test_foundations_always_count(self) -> None:
        reports = foundations()
        reports[0] = report(reports[0].check.name, FAIL, place(FAIL))
        self.assertEqual(scored(reports).depth, 5 * 10 + 5)  # five core foundations and the licence


class OpportunityTests(unittest.TestCase):
    def test_the_next_level_s_blockers_come_first(self) -> None:
        reports = foundations()
        reports[2] = report(reports[2].check.name, FAIL, place(FAIL))
        reports.append(report("static-analysis", FAIL, place(FAIL)))
        first = scored(reports).opportunities[0]
        self.assertEqual((first.check, first.unlocks, first.blocks), (reports[2].check.name, 1, 1))
        self.assertIn("unlocks Level 1", first.describe())

    def test_an_opportunity_says_what_it_is_worth(self) -> None:
        reports = [*foundations(), report("static-analysis", FAIL, place(PASS), place(FAIL, ecosystem="Python"))]
        (opportunity,) = scored(reports).opportunities
        self.assertEqual((opportunity.ecosystem, opportunity.unit, opportunity.tier), ("Python", ".", "core"))
        self.assertAlmostEqual(opportunity.completeness, 1 / 7 / 2)  # one of unit "."'s 7 cells; 2 units
        self.assertEqual(opportunity.depth, 10)
        self.assertIsNone(opportunity.unlocks)  # the rest of level 2's checks did not run

    def test_a_locked_level_s_opportunity_earns_no_depth_yet(self) -> None:
        (opportunity,) = scored(report("sanitizers", FAIL, place(FAIL))).opportunities
        self.assertEqual(opportunity.depth, 0)

    def test_every_blocker_of_the_next_level_ranks_above_other_cells(self) -> None:
        reports = foundations()
        reports[1] = report(reports[1].check.name, FAIL, place(FAIL), place(FAIL, ecosystem="Shell"))
        reports.append(report("security-policy", FAIL))
        reports.append(report("static-analysis", FAIL, *(place(FAIL, unit=str(n)) for n in range(3))))
        ranked = scored(reports).opportunities
        self.assertEqual([(o.check, o.blocks) for o in ranked[:2]], [(reports[1].check.name, 1)] * 2)
        self.assertEqual({o.unlocks for o in ranked}, {None})
        self.assertIn("toward Level 1", ranked[0].describe())
        self.assertEqual(ranked[-1].check, "security-policy")

    def test_core_opportunities_rank_above_auxiliary_ones(self) -> None:
        reports = [
            report("coverage", FAIL, place(FAIL, ecosystem="Python", auxiliary=("scripts",))),
            report("type-checking", FAIL, place(FAIL)),
        ]
        self.assertEqual([o.check for o in scored(reports).opportunities], ["type-checking", "coverage"])

    def test_how_an_opportunity_is_described(self) -> None:
        reports = [
            report("sanitizers", FAIL, place(FAIL, unit="lib")),
            project_wide("security-policy", WARN),
            report("fuzz-testing", FAIL, place(SKIP), place(FAIL)),
        ]
        described = sorted(o.describe() for o in scored(reports).opportunities)
        self.assertEqual(
            described,
            [
                "fuzz-testing (C/C++ in the root): +33.3% completeness",
                "sanitizers (C/C++ in unit lib): +33.3% completeness",  # one of three units
                "security-policy: +16.7% completeness",
            ],
        )

    def test_a_covered_project_has_none(self) -> None:
        self.assertEqual(scored(foundations()).opportunities, ())


class ScoreOutputTests(unittest.TestCase):
    def test_the_summary_line(self) -> None:
        result = scored(foundations(), report("static-analysis", FAIL, place(FAIL)))
        self.assertEqual(result.summary(), "Level 1 · 91% complete · 60 depth")

    def test_completeness_is_shown_rounded_down(self) -> None:
        reports = [report("tests-run", FAIL, *(place(PASS, unit=str(n)) for n in range(199)), place(FAIL, unit="x"))]
        self.assertIn("99% complete", scored(reports).summary())

    def test_as_dict_carries_the_version_and_every_part(self) -> None:
        reports = foundations()
        reports.append(report("coverage", FAIL, place(FAIL)))
        as_dict = json.loads(json.dumps(scored(reports).as_dict()))
        self.assertEqual(as_dict["version"], SCORE_VERSION)
        self.assertTrue(as_dict["preview"])
        self.assertEqual(
            set(as_dict),
            {"version", "preview", "level", "completeness", "depth", "locked_depth", "cells", "opportunities"},
        )
        cell = next(cell for cell in as_dict["cells"] if cell["check"] == "coverage")
        self.assertEqual(
            cell,
            {
                "check": "coverage",
                "level": 2,
                "ecosystem": "C/C++",
                "unit": ".",
                "tier": "core",
                "status": "FAIL",
                "tools": [],
                "points": 0,
                "counted": True,
            },
        )
        (opportunity,) = as_dict["opportunities"]
        self.assertEqual(opportunity["check"], "coverage")
        self.assertIsNone(opportunity["unlocks"])  # the rest of level 2's checks did not run


def _run(*arguments: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(arguments))
    return code, out.getvalue()


class ScoreOptionTests(unittest.TestCase):
    PROJECT = str(FIXTURES / "well_configured_python")
    BARE = str(FIXTURES / "bare_python")

    def test_text_ends_with_the_score_and_the_top_opportunities(self) -> None:
        code, output = _run(self.BARE, "--score", "--color", "never")
        self.assertEqual(code, EXIT_FAILURE)
        tail = output.split("\n\nScore (preview v0): ", 1)[1]
        self.assertRegex(tail, r"^Level 0 · \d+% complete · \d+ depth\nNext:\n  - ")
        self.assertLessEqual(tail.count("\n  - "), 5)

    def test_a_complete_project_has_no_next_steps(self) -> None:
        _, output = _run(self.PROJECT, "--score", "--color", "never", "--only", "license")
        self.assertTrue(output.endswith("Score (preview v0): Level 0 · 100% complete · 5 depth\n"), output)

    def test_json_puts_the_results_beside_the_score(self) -> None:
        code, output = _run(self.PROJECT, "--score", "--format", "json")
        plain_code, plain = _run(self.PROJECT, "--format", "json")
        loaded = json.loads(output)
        self.assertEqual(set(loaded), {"results", "score"})
        self.assertEqual(loaded["results"], json.loads(plain))
        self.assertEqual((code, plain_code), (EXIT_SUCCESS, EXIT_SUCCESS))
        self.assertEqual(loaded["score"]["version"], SCORE_VERSION)
        self.assertGreaterEqual(loaded["score"]["level"], 1)

    def test_markdown_ends_with_the_score(self) -> None:
        _, output = _run(self.BARE, "--score", "--format", "markdown")
        self.assertIn("\n\n**Score (preview v0):** Level 0 · ", output)

    def test_the_score_does_not_change_the_exit_code(self) -> None:
        for project in (self.PROJECT, self.BARE):
            with self.subTest(project=project):
                self.assertEqual(_run(project, "--score")[0], _run(project)[0])


if __name__ == "__main__":
    unittest.main()
