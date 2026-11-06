"""The coverage question: for one language, what coverage does CI report, at each granularity?"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from project_validator.facts import Facts, Unknown
from project_validator.facts.coverage import CoverageMeasured, CoverageTool, Granularity
from project_validator.questions import Answer


@dataclass(frozen=True, slots=True, kw_only=True)
class GranularityAnswer:
    """`tools`: those CI runs that report it (for yes). `known`: how the known tools report it."""

    answer: Answer
    tools: tuple[str, ...] = ()
    known: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageAnswer:
    language: str
    granularities: Mapping[Granularity, GranularityAnswer]
    # What could not be read, for unknown answers: `subject: reason (origin)`.
    unknowns: tuple[str, ...] = ()

    def __getitem__(self, granularity: Granularity) -> GranularityAnswer:
        return self.granularities[granularity]

    def possible(self) -> tuple[Granularity, ...]:
        """The granularities a known tool can measure for the language, coarsest first."""
        return tuple(found for found, answer in self.granularities.items() if answer.answer is not Answer.IMPOSSIBLE)

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            **{
                str(granularity): {"answer": str(found.answer), "tools": list(found.tools), "known": list(found.known)}
                for granularity, found in self.granularities.items()
            },
            "unknowns": list(self.unknowns),
        }


def _answer(
    granularity: Granularity, measured: tuple[CoverageMeasured, ...], known: tuple[CoverageTool, ...], unread: bool
) -> GranularityAnswer:
    able = tuple(dict.fromkeys(tool.can[granularity] for tool in known if granularity in tool.can))
    if not able:
        return GranularityAnswer(answer=Answer.IMPOSSIBLE)
    if tools := tuple(dict.fromkeys(fact.tool for fact in measured if granularity in fact.granularities)):
        return GranularityAnswer(answer=Answer.YES, tools=tools, known=able)
    return GranularityAnswer(answer=Answer.UNKNOWN if unread else Answer.NO, known=able)


def coverage_answer(language: str, facts: Facts, tools: Iterable[CoverageTool]) -> CoverageAnswer:
    """What coverage CI reports for `language`, by the facts, and what the known `tools` could report."""
    known = tuple(tool for tool in tools if language in tool.languages)
    measured = tuple(fact for fact in facts.of(CoverageMeasured) if language in fact.languages)
    unknowns = tuple(f"{fact.subject}: {fact.reason} ({fact.origin})" for fact in facts.of(Unknown))
    return CoverageAnswer(
        language=language,
        granularities={
            granularity: _answer(granularity, measured, known, bool(unknowns)) for granularity in Granularity
        },
        unknowns=unknowns,
    )


__all__ = ["CoverageAnswer", "GranularityAnswer", "coverage_answer"]
