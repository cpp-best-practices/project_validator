"""The coverage question, answered from facts, and the coverage policy that judges the answers."""

import unittest
from unittest import mock

from project_validator.checks.coverage import coverage
from project_validator.core import Context, Result, Status
from project_validator.facts import Command, Facts, Origin, Unknown
from project_validator.facts.coverage import CoverageMeasured, CoverageTool, Granularity, Measurement, measured
from project_validator.policy import judge_coverage, required_coverage
from project_validator.questions import Answer
from project_validator.questions.coverage import coverage_answer
from tests.support import github_job, make_context, temp_project

ORIGIN = Origin(path="ci.yml", at=("jobs", "test"))


def _never(_: Command, __: Context) -> Measurement | None:
    return None


def _tool(name: str, languages: set[str], *granularities: Granularity) -> CoverageTool:
    return CoverageTool(
        name=name,
        languages=frozenset(languages),
        can={granularity: f"{name} --{granularity}" for granularity in granularities},
        measures=_never,
    )


def _measured(tool: str, *granularities: Granularity) -> CoverageMeasured:
    return CoverageMeasured(
        origin=ORIGIN, job="test", tool=tool, languages=frozenset({"Lang"}), granularities=frozenset(granularities)
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
        c_only = CoverageTool(
            name="ccov", languages=frozenset({"C"}), can={BRANCH: "ccov"}, measures=lambda *_: measured(BRANCH)
        )
        files = {"main.c": "", "app.cpp": "", **github_job("ubuntu-latest", "ccov")}
        with (
            mock.patch("project_validator.checks.coverage.built_in_coverage_tools", return_value=(c_only,)),
            mock.patch("project_validator.facts.coverage.built_in_coverage_tools", return_value=(c_only,)),
            temp_project(files) as root,
        ):
            result = coverage.run(make_context(root))
        self.assertEqual(
            result.message, "C: branch coverage is reported with ccov; C++: no known tool measures the coverage of C++"
        )
