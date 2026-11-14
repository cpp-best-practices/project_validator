"""The coverage question: for each language, in each unit of the project that has it, what coverage does CI report,
at each granularity?"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from project_validator.facts import ActionStep, Command, Facts, resolved
from project_validator.facts.arguments import program
from project_validator.facts.coverage import COVERAGE, Granularity, Rung, level, rung_of
from project_validator.facts.tools import Tool, ToolRun, known_tools
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, per_unit, runs_of, unknowns_for
from project_validator.tools.coverage_services import CODECOV, CODECOV_TARGET, UPLOAD_ACTIONS, UPLOADERS


@dataclass(frozen=True, slots=True, kw_only=True)
class GranularityAnswer:
    """`tools`: those CI runs that measure it (for yes), `reported` and `gated` those that take it to that rung, and
    `rung` the highest reached. `known`: how the known tools measure it."""

    answer: Answer
    rung: Rung | None = None
    tools: tuple[str, ...] = ()
    reported: tuple[str, ...] = ()
    gated: tuple[str, ...] = ()
    known: tuple[str, ...] = ()

    def at(self, rung: Rung) -> tuple[str, ...]:
        """The tools that take the granularity to `rung`."""
        return {Rung.MEASURED: self.tools, Rung.REPORTED: self.reported, Rung.GATED: self.gated}[rung]


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageAnswer:
    """The coverage of one language in one unit ("." for the project's root unit)."""

    language: str
    unit: str = "."
    granularities: Mapping[Granularity, GranularityAnswer]
    # What could not be read, for unknown answers: `subject: reason (origin)`.
    unknowns: tuple[str, ...] = ()

    def __getitem__(self, granularity: Granularity) -> GranularityAnswer:
        return self.granularities[granularity]

    def possible(self) -> tuple[Granularity, ...]:
        """The granularities a known tool can measure for the language, coarsest first."""
        return tuple(found for found, answer in self.granularities.items() if answer.answer is not Answer.IMPOSSIBLE)

    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran that reports some granularity, each once, in order."""
        return tuple(dict.fromkeys(tool for found in self.granularities.values() for tool in found.tools))

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            **{
                str(granularity): {
                    "answer": str(found.answer),
                    "rung": str(found.rung) if found.rung else None,
                    "tools": list(found.tools),
                    "reported": list(found.reported),
                    "gated": list(found.gated),
                    "known": list(found.known),
                }
                for granularity, found in self.granularities.items()
            },
            unknowns=list(self.unknowns),
        )


type LanguageCoverage = LanguageAnswers[CoverageAnswer]


def measures_coverage(tool: Tool) -> bool:
    return COVERAGE in tool.can


def _answer(
    granularity: Granularity, runs: tuple[ToolRun, ...], known: tuple[Tool, ...], unread: bool
) -> GranularityAnswer:
    name = str(granularity)
    able = tuple(dict.fromkeys(tool.can[COVERAGE][name] for tool in known if name in tool.can[COVERAGE]))
    if not able:
        return GranularityAnswer(answer=Answer.IMPOSSIBLE)
    at = {
        rung: tuple(dict.fromkeys(run.tool for run in runs if level(granularity, rung) in run.provides[COVERAGE]))
        for rung in Rung
    }
    if at[Rung.MEASURED]:
        reached = max(
            (rung_of(run.provides[COVERAGE], granularity) or Rung.MEASURED for run in runs), key=lambda rung: rung.rank
        )
        return GranularityAnswer(
            answer=Answer.YES,
            rung=reached,
            tools=at[Rung.MEASURED],
            reported=at[Rung.REPORTED],
            gated=at[Rung.GATED],
            known=able,
        )
    return GranularityAnswer(answer=Answer.UNKNOWN if unread else Answer.NO, known=able)


def _uploading_jobs(facts: Facts) -> frozenset[str]:
    """The jobs that upload a coverage report to a coverage service."""
    actions = (step.job for step in facts.of(ActionStep) if step.uses.partition("@")[0] in UPLOAD_ACTIONS)
    programs = (command.job for command in facts.of(Command) if program(resolved(command)) in UPLOADERS)
    return frozenset((*actions, *programs))


def _uploaded(run: ToolRun, rung: Rung) -> ToolRun:
    """`run` as a run whose report a service shows (and, `rung` gated, gates): its measured granularities raised."""
    levels = run.provides.get(COVERAGE, frozenset())
    measured = [found for found in Granularity if str(found) in levels]
    raised = {level(found, step) for found in measured for step in Rung if step.rank <= rung.rank}
    return replace(run, provides={**run.provides, COVERAGE: frozenset(levels) | raised})


def _with_uploads(runs: tuple[ToolRun, ...], facts: Facts) -> tuple[ToolRun, ...]:
    """The coverage runs, those of a job that uploads the report to Codecov or Coveralls reported there (and gated,
    where codecov.yml sets a status target)."""
    jobs = _uploading_jobs(facts)
    if not jobs:
        return runs
    rung = Rung.GATED if facts.setting(CODECOV, CODECOV_TARGET) is not None else Rung.REPORTED
    return tuple(_uploaded(run, rung) if run.job in jobs else run for run in runs)


def coverage_answer(
    language: str, facts: Facts, tools: Iterable[Tool], unit: str = ".", auxiliary: tuple[str, ...] = ()
) -> CoverageAnswer:
    """What coverage CI reports for `language` in `unit` (for the auxiliary code `auxiliary` names, when the answer
    is about that), by the facts, and what the known `tools` could report."""
    known = tuple(tool for tool in tools if measures_coverage(tool) and language in tool.languages)
    runs = _with_uploads(runs_of(COVERAGE, language, unit, facts, auxiliary=auxiliary), facts)
    unknowns = unknowns_for(known, facts)
    return CoverageAnswer(
        language=language,
        unit=unit,
        granularities={granularity: _answer(granularity, runs, known, bool(unknowns)) for granularity in Granularity},
        unknowns=unknowns,
    )


def language_coverage(language: str, facts: Facts) -> LanguageCoverage:
    tools = known_tools()
    return per_unit(language, facts, lambda unit, roles: coverage_answer(language, facts, tools, unit, roles))


COVERAGE_QUESTION = Question(
    name="coverage",
    description="What coverage does CI report for each language in each unit, at each granularity (line to path)?",
    answer=language_coverage,
)

__all__ = [
    "COVERAGE_QUESTION",
    "CoverageAnswer",
    "GranularityAnswer",
    "LanguageCoverage",
    "coverage_answer",
    "language_coverage",
    "measures_coverage",
]
