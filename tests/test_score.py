"""The tooling score, version 1 (upstream #295): 100% means every quality gate that applies to each part of the
project is in place, and extra credit above 100% rewards complementary tools, once every gate is. Statuses and exit
codes do not change; the score is read from the reports alone."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE, main
from project_validator.core import Check, Placed, Result, Status
from project_validator.runner import Report
from project_validator.score import (
    FINDINGS,
    FLOOR,
    LEVEL_NAMES,
    LEVELS,
    NOT_FOR_AUXILIARY,
    SCORE_VERSION,
    UNSCORED,
    Score,
    family,
    score,
    shortfalls,
    sizes,
)
from tests.support import FIXTURES, make_context, temp_project
from tests.test_cli import run_cli

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

    def test_a_gate_whose_tools_reach_part_of_the_code_fills_that_share(self) -> None:
        partial = Placed(ecosystem="Python", unit=".", result=Result(status=PASS, message="", share=0.5))
        reports = [report("tests-run", PASS, place(PASS)), report("static-analysis", PASS, partial)]
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

    def test_what_the_validator_finds_itself_can_take_points_away_but_never_add_them(self) -> None:
        """Only processes the project puts in place earn points. A check that passes because the validator found no
        defect itself (every data file parses, nothing large or built is committed) is no slot; one that finds a
        defect is a slot nothing fills, so it costs its share and is a next step."""
        self.assertEqual(
            FINDINGS,
            {"data-wellformed", "repository-hygiene", "committed-artifacts", "large-files", "ci-current"},
        )
        for name in FINDINGS:
            with self.subTest(check=name):
                passing = scored(report("tests-run", FAIL, place(FAIL)), report(name, PASS, place(PASS)))
                self.assertEqual((passing.filled, passing.slots), (0, 1))
                for status in (WARN, FAIL):
                    found = scored(report("tests-run", PASS, place(PASS)), report(name, status, place(status)))
                    self.assertEqual((found.filled, found.slots), (1, 2))
                    self.assertEqual([step.check for step in found.next_steps], [name])
                low = scored(report("tests-run", FAIL, place(FAIL)), report(name, WARN, place(WARN)))
                self.assertEqual(low.filled, 0)  # a warning never adds, even to a low score
        project = scored(report("tests-run", PASS, place(PASS)), project_wide("ci-current", FAIL))
        self.assertEqual((project.filled, project.slots), (1, 2))
        self.assertEqual(scored(report("tests-run", PASS, place(PASS)), project_wide("ci-current", PASS)).slots, 1)

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

    def test_the_units_breakdown_is_by_unit(self) -> None:
        reports = [
            report("tests-run", PASS, place(PASS, unit="lib"), place(FAIL, unit="app"), place(PASS, unit="app")),
            project_wide("license", PASS),
        ]
        found = scored(reports)
        self.assertEqual(found.units(), {"lib": (1, 1), "app": (1, 2), "": (1, 1)})
        self.assertTrue(found.several_units)
        self.assertEqual(found.as_dict()["units"], {"lib": [1, 1], "app": [1, 2], "": [1, 1]})

    def test_one_unit_is_not_several(self) -> None:
        self.assertFalse(scored(foundations()).several_units)

    def test_as_json(self) -> None:
        data = scored(foundations()).as_dict()
        self.assertEqual(data["version"], SCORE_VERSION)
        self.assertEqual(SCORE_VERSION, "3")  # 2: weighted by size (upstream #331); 3: findings only take away
        self.assertEqual(data["percent"], 100)
        self.assertEqual((data["level"], data["level_name"]), (1, "Foundations"))
        self.assertEqual((data["filled"], data["slots"], data["extra"], data["held"]), (7, 7, 0, 0))
        cells = data["cells"]
        self.assertIsInstance(cells, list)
        self.assertEqual(len(cells) if isinstance(cells, list) else 0, 7)
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
        self.assertEqual(set(data), {"format", "version", "results", "score"})
        self.assertLess(data["score"]["percent"], 100)

    def test_the_next_steps_are_listed(self) -> None:
        _, output = self._run("--score", "--color", "never", str(FIXTURES / "bare_python"))
        self.assertIn("Next steps:", output)


class GateTests(unittest.TestCase):
    """`--min-level` and `--min-completeness` (upstream #295): opt-in floors that fail the run when the score is below
    them; without them the exit code is the statuses' alone."""

    def test_a_score_at_or_above_the_floors_falls_short_of_nothing(self) -> None:
        level_1 = scored(foundations())
        self.assertEqual(shortfalls(level_1, min_level=1, min_completeness=100), [])
        self.assertEqual(shortfalls(level_1), [])

    def test_a_lower_level_falls_short(self) -> None:
        level_1 = scored(foundations())
        self.assertEqual(shortfalls(level_1, min_level=2), ["Level 1 Foundations is below --min-level 2"])

    def test_the_share_of_the_gates_in_place_is_the_completeness(self) -> None:
        missing = scored(foundations(), report("static-analysis", FAIL, place(FAIL)))
        self.assertEqual(shortfalls(missing, min_completeness=87.5), [])
        self.assertEqual(
            shortfalls(missing, min_completeness=88, min_level=2),
            [
                "Level 1 Foundations is below --min-level 2",
                "87.5% of the gates in place is below --min-completeness 88",
            ],
        )

    def test_extra_credit_is_no_completeness(self) -> None:
        extra = scored(foundations(), report("static-analysis", PASS, place(PASS, "clang-tidy", "cppcheck")))
        self.assertGreater(extra.percent, 100)
        self.assertEqual(shortfalls(extra, min_completeness=100), [])


class GateCliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> tuple[int, str]:
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            code = main([*arguments])
        return code, errors.getvalue()

    def test_a_score_below_a_floor_fails_a_run_that_passes(self) -> None:
        project = str(FIXTURES / "well_configured_python")
        self.assertEqual(self._run("--only", "license", project)[0], EXIT_SUCCESS)
        self.assertEqual(self._run("--only", "license", "--min-completeness", "100", project)[0], EXIT_SUCCESS)
        code, errors = self._run("--only", "license", "--min-level", "1", project)
        self.assertEqual(code, EXIT_FAILURE)
        self.assertIn("score below its floor: Level 0 Getting started is below --min-level 1", errors)

    def test_a_complete_project_meets_every_floor(self) -> None:
        project = str(FIXTURES / "well_configured_python")
        code, errors = self._run("--min-level", "4", "--min-completeness", "100", project)
        self.assertEqual((code, errors), (EXIT_SUCCESS, ""))

    def test_the_floors_are_checked_against_their_range(self) -> None:
        for arguments in (
            ("--min-level", "5"),
            ("--min-level", "-1"),
            ("--min-completeness", "101"),
            ("--min-completeness", "most"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as raised:
                self._run(*arguments, str(FIXTURES / "bare_python"))
            self.assertEqual(raised.exception.code, EXIT_USAGE)

    def test_a_floor_needs_a_score(self) -> None:
        for dump in ("--facts", "--map", "--answers", "--tui"):
            with self.subTest(dump=dump):
                code, errors = self._run(dump, "--min-level", "1", str(FIXTURES / "bare_python"))
                self.assertEqual(code, EXIT_USAGE)
                self.assertIn(f"--min-level and --min-completeness need the analysis, not {dump}", errors)


if __name__ == "__main__":
    unittest.main()


SIZES = {("Rust", "."): 0.95, ("Shell", "."): 0.05}


class SizeTests(unittest.TestCase):
    """Each language's slots weigh its share of its unit's product lines, at least 10% (upstream #331): a few helper
    scripts don't count as much as the main language. Levels, auxiliary and project slots are unchanged."""

    def test_a_small_languages_gap_costs_less_than_the_main_ones(self) -> None:
        rust_gap = [report("static-analysis", FAIL, place(FAIL, ecosystem="Rust"), place(PASS, ecosystem="Shell"))]
        shell_gap = [report("static-analysis", FAIL, place(PASS, ecosystem="Rust"), place(FAIL, ecosystem="Shell"))]
        self.assertEqual(round(score(rust_gap, sizes=SIZES).percent), 10)  # 0.1 of 1.05
        self.assertEqual(round(score(shell_gap, sizes=SIZES).percent), 90)
        [step] = score(shell_gap, sizes=SIZES).next_steps
        [bigger] = score(rust_gap, sizes=SIZES).next_steps
        self.assertLess(step.points, bigger.points)

    def test_a_tiny_share_still_weighs_the_floor(self) -> None:
        cells = score([report("tests-run", PASS, place(PASS, ecosystem="Shell"))], sizes={("Shell", "."): 0.001}).cells
        self.assertEqual(cells[0].weight, 0.1)

    def test_project_and_auxiliary_slots_and_a_single_language_score_as_before(self) -> None:
        reports = [project_wide("license", PASS), report("tests-run", FAIL, place(FAIL, auxiliary=("tooling",)))]
        weights = [cell.weight for cell in score(reports, sizes={("C++", "."): 0.2}).cells]
        self.assertEqual(weights, [1.0, 0.5])
        alone = [report("tests-run", PASS, place(PASS)), report("coverage", FAIL, place(FAIL))]
        self.assertEqual(scored(alone).percent, score(alone, sizes={("C++", "."): 1.0}).percent)

    def test_every_slot_must_still_be_filled_for_100_percent(self) -> None:
        reports = [report("tests-run", PASS, place(PASS, ecosystem="Rust"), place(WARN, ecosystem="Shell"))]
        self.assertLess(score(reports, sizes=SIZES).percent, 100)

    def test_a_languages_share_is_of_its_units_product_lines(self) -> None:
        files = {
            "Cargo.toml": "[package]\nname = 'app'\n",
            "src/main.rs": "fn main() {}\n" * 18,
            "build.sh": "echo hi\n",
            "tests/check.sh": "echo test\n" * 100,  # test code: not the product's
        }
        with temp_project(files) as root:
            shares = sizes(make_context(root).facts)
        # 18 lines of Rust, 1 of Shell and Cargo.toml's 2 of TOML (the Data format): a format's lines count too.
        found = {key: round(share, 3) for key, share in shares.items()}
        self.assertEqual(found, {("Rust", "."): 0.857, ("Shell", "."): 0.048, ("Data", "."): 0.095})

    def test_a_unit_whose_files_hold_no_lines_has_no_sizes(self) -> None:
        with temp_project({"src/main.rs": "", "Cargo.toml": ""}) as root:
            self.assertEqual(sizes(make_context(root).facts), {})

    def test_the_run_weighs_each_languages_slots_by_its_size(self) -> None:
        # The script is in a source folder: a root one would be a stray file's language, auxiliary (#182).
        files = {"CMakeLists.txt": "project(app CXX)\n", "src/main.cpp": "int x;\n" * 98, "src/build.sh": "echo hi\n"}
        with temp_project(files) as root:
            _, output, _ = run_cli("--score", "--format", "json", str(root))
        weights = {cell["ecosystem"]: cell["weight"] for cell in json.loads(output)["score"]["cells"]}
        self.assertEqual(weights["Shell"], FLOOR)  # 1 of 100 lines
        self.assertGreater(weights["C++"], 0.9)
