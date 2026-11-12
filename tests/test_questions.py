"""The coverage question, answered from facts, and the coverage policy that judges the answers."""

from __future__ import annotations

import unittest
from typing import cast
from unittest import mock

from project_validator.checks.coverage import coverage
from project_validator.core import Result, Status
from project_validator.ecosystems import isolated_registry, register
from project_validator.facts import Command, Facts, Origin, Unknown
from project_validator.facts.coverage import COVERAGE, Granularity, coverage_tool, measured
from project_validator.facts.structure import Unit
from project_validator.facts.tools import Run, Tool, ToolRun
from project_validator.policy.coverage import judge_coverage, required_coverage
from project_validator.questions import FORMATS, LANGUAGES, Answer, answer_dict, known_questions, units_of, unknowns_for
from project_validator.questions.answers import answers
from project_validator.questions.coverage import coverage_answer
from tests.support import FORMAT_ECOSYSTEM, github_job, make_context, temp_project

ORIGIN = Origin(path="ci.yml", at=("jobs", "test"))


class AnswerDictTests(unittest.TestCase):
    def test_every_answer_starts_with_its_language_unit_and_verdict(self) -> None:
        answer = coverage_answer("Lang", Facts(), ())
        self.assertEqual(
            answer_dict(answer, Answer.YES, extra=[1]), {"language": "Lang", "unit": ".", "answer": "yes", "extra": [1]}
        )
        self.assertEqual(answer_dict(answer), {"language": "Lang", "unit": "."})


class UnknownsForTests(unittest.TestCase):
    def test_unknown_settings_count_for_what_is_read(self) -> None:
        settings = Unknown(origin=ORIGIN, subject="s", reason="not read", hides="settings", tools=("CMake",))
        commands = Unknown(origin=ORIGIN, subject="c", reason="not split")
        facts = Facts((settings, commands))
        self.assertEqual(unknowns_for((), facts), ("c: not split (ci.yml:jobs.test)",))
        self.assertEqual(len(unknowns_for((), facts, reads=("CMake",))), 2)
        self.assertEqual(len(unknowns_for((), facts, reads=("Meson",))), 1)


def _never(_: Command, __: Facts) -> Run | None:
    return None


def _tool(name: str, languages: set[str], *granularities: Granularity) -> Tool:
    return coverage_tool(
        name=name,
        languages=frozenset(languages),
        can={granularity: f"{name} --{granularity}" for granularity in granularities},
        measures=_never,
    )


def _measured(tool: str, *granularities: Granularity, scope: tuple[str, ...] = (".",)) -> ToolRun:
    return ToolRun(
        origin=ORIGIN,
        job="test",
        tool=tool,
        languages=frozenset({"Lang"}),
        provides={COVERAGE: frozenset(granularities)},
        scope=scope,
    )


LINE, STATEMENT, BRANCH, PATH = Granularity.LINE, Granularity.STATEMENT, Granularity.BRANCH, Granularity.PATH
TOOLS = (_tool("cov", {"Lang"}, LINE, BRANCH), _tool("paths", {"Lang"}, PATH), _tool("other", {"Other"}, BRANCH))


class CoverageAnswerTests(unittest.TestCase):
    def test_yes_no_and_impossible_by_what_the_known_tools_measure(self) -> None:
        answer = coverage_answer("Lang", Facts((_measured("cov", LINE),)), TOOLS)
        self.assertEqual(
            {granularity: found.answer for granularity, found in answer.granularities.items()},
            {
                LINE: Answer.YES,
                STATEMENT: Answer.IMPOSSIBLE,
                Granularity.REGION: Answer.IMPOSSIBLE,
                BRANCH: Answer.NO,
                PATH: Answer.NO,
            },
        )
        self.assertEqual(answer[LINE].tools, ("cov",))
        self.assertEqual(answer[BRANCH].known, ("cov --branch",))

    def test_what_could_not_be_read_makes_no_unknown(self) -> None:
        unread = Unknown(origin=ORIGIN, subject="the jobs", reason="a matrix computed by an expression")
        answer = coverage_answer("Lang", Facts((unread, _measured("cov", BRANCH))), TOOLS)
        self.assertEqual((answer[BRANCH].answer, answer[PATH].answer), (Answer.YES, Answer.UNKNOWN))
        self.assertEqual(answer.unknowns, ("the jobs: a matrix computed by an expression (ci.yml:jobs.test)",))

    def test_answers_are_json_ready(self) -> None:
        found = coverage_answer("Lang", Facts((_measured("cov", BRANCH),)), TOOLS).as_dict()
        self.assertEqual(found["branch"], {"answer": "yes", "tools": ["cov"], "known": ["cov --branch"]})
        self.assertEqual(found["language"], "Lang")


class CoveragePolicyTests(unittest.TestCase):
    def test_branch_coverage_is_required_or_else_the_finest_possible(self) -> None:
        self.assertEqual(required_coverage(coverage_answer("Lang", Facts(), TOOLS)), BRANCH)
        statements = (_tool("go", {"Lang"}, LINE, STATEMENT),)
        self.assertEqual(required_coverage(coverage_answer("Lang", Facts(), statements)), STATEMENT)

    def test_a_language_no_tool_measures_is_skipped(self) -> None:
        self.assertEqual(
            judge_coverage(coverage_answer("Zig", Facts(), TOOLS)),
            Result(status=Status.SKIP, message="no known tool measures the coverage of Zig"),
        )

    def test_path_coverage_is_a_bonus(self) -> None:
        judged = judge_coverage(coverage_answer("Lang", Facts((_measured("cov", BRANCH),)), TOOLS))
        self.assertEqual(
            judged,
            Result.passed("branch coverage is reported with cov", "consider adding path coverage (e.g. paths --path)"),
        )
        both = Facts((_measured("cov", BRANCH), _measured("paths", PATH)))
        self.assertEqual(
            judge_coverage(coverage_answer("Lang", both, TOOLS)).message,
            "branch coverage is reported with cov; path coverage bonus: paths",
        )


class LanguagesOfOneEcosystemTests(unittest.TestCase):
    def test_languages_judged_differently_are_labelled(self) -> None:
        c_only = coverage_tool(
            name="ccov", languages=frozenset({"C"}), can={BRANCH: "ccov"}, measures=lambda *_: measured(BRANCH)
        )
        cxx_lines = coverage_tool(
            name="xxcov", languages=frozenset({"C++"}), can={LINE: "xxcov"}, measures=lambda *_: measured(LINE)
        )
        files = {"main.c": "", "app.cpp": "", **github_job("ubuntu-latest", "ccov")}
        with (
            mock.patch("project_validator.questions.coverage.known_tools", return_value=(c_only, cxx_lines)),
            mock.patch("project_validator.facts.tools.known_tools", return_value=(c_only, cxx_lines)),
            temp_project(files) as root,
        ):
            result = coverage.run(make_context(root))
        self.assertEqual(
            result.message,
            "C: branch coverage is reported with ccov; C++: line coverage is reported with xxcov",
        )
        # A language no known tool handles is not judged by the check at all.
        with (
            mock.patch("project_validator.questions.coverage.known_tools", return_value=(c_only,)),
            mock.patch("project_validator.facts.tools.known_tools", return_value=(c_only,)),
            temp_project(files) as root,
        ):
            self.assertEqual(coverage.run(make_context(root)).message, "branch coverage is reported with ccov")


class UnitTests(unittest.TestCase):
    def test_a_run_covers_its_directory_what_is_below_it_and_the_unit_it_is_in(self) -> None:
        units = (".", "packages/a", "packages/a/sub", "packages/b", "packages/ab")
        run = _measured("cov", BRANCH, scope=("packages/a",))
        # A workspace member is a unit of its own: a run in it does not cover the root unit above it.
        self.assertEqual([run.covers(unit, units) for unit in units], [False, True, True, False, False])
        self.assertTrue(_measured("cov", BRANCH).covers("packages/b", units))
        # A run in a directory of a unit (its `src/`) covers that unit.
        inside = _measured("cov", BRANCH, scope=("packages/a/src",))
        self.assertEqual([inside.covers(unit, units) for unit in units], [False, True, False, False, False])
        self.assertTrue(_measured("cov", BRANCH, scope=("src",)).covers(".", units))

    def test_a_format_is_answered_in_the_units_whose_files_are_in_it(self) -> None:
        facts = Facts(
            (
                Unit(origin=Origin(path="."), build_systems=(), languages=frozenset(), formats=frozenset({"WDATA"})),
                Unit(origin=Origin(path="b"), build_systems=("npm",), languages=frozenset({"Lang"})),
            )
        )
        self.assertEqual((units_of("WDATA", facts), units_of("Lang", facts)), ((".",), ("b",)))
        self.assertEqual(units_of("WDATA", Facts()), (".",))

    def test_every_question_is_asked_of_the_languages_or_formats_it_is_about(self) -> None:
        with isolated_registry(), temp_project({"src/a.wdata": "", "setup.py": ""}) as root:
            register(FORMAT_ECOSYSTEM)
            found = answers(make_context(root))
        kinds = {question.name: question.kinds for question in known_questions()}
        self.assertEqual((kinds["coverage"], kinds["wellformed"]), (LANGUAGES, FORMATS))
        for question, entries in found.items():
            with self.subTest(question=question):
                expected = [*["Python"] * ("language" in kinds[question]), *["WDATA"] * ("format" in kinds[question])]
                asked = [entry["language"] for entry in cast("list[dict[str, object]]", entries)]
                self.assertEqual(asked, expected)

    def test_each_unit_of_a_language_is_answered(self) -> None:
        facts = Facts(
            (
                Unit(origin=Origin(path="a"), build_systems=("npm",), languages=frozenset({"Lang"})),
                Unit(origin=Origin(path="b"), build_systems=("npm",), languages=frozenset({"Lang"})),
                _measured("cov", BRANCH, scope=("a",)),
            )
        )
        answers = {unit: coverage_answer("Lang", facts, TOOLS, unit)[BRANCH].answer for unit in ("a", "b")}
        self.assertEqual(answers, {"a": Answer.YES, "b": Answer.NO})
