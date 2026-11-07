"""Coverage facts: what each coverage tool that CI runs measures, and what each known tool can measure.

A `CoverageTool` records its whole upstream capability, keyed by the languages it measures (never by a profile), and
claims the commands that run it. A command it claims becomes a `CoverageMeasured` fact, joined with the
configuration that command reads: a setting counts only when CI runs the tool that reads it.
"""

import enum
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from project_validator.facts import Command, Fact, Facts, Origin

if TYPE_CHECKING:
    from project_validator.core import Context


class Granularity(enum.StrEnum):
    """What a coverage measurement counts, from coarsest to finest.

    `path` stands for the coverage of combinations of decisions: path, prime path, condition and MC/DC coverage.
    """

    LINE = "line"
    STATEMENT = "statement"
    REGION = "region"
    BRANCH = "branch"
    PATH = "path"

    @property
    def rank(self) -> int:
        return tuple(Granularity).index(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class Measurement:
    """What one run of a tool measures, and the configuration files it read to decide."""

    granularities: frozenset[Granularity]
    read: tuple[str, ...] = ()
    # Matched in text that is not parsed (a compiler flag somewhere in a CMake file) rather than read.
    heuristic: bool = False


type Measure = Callable[[Command, Context], Measurement | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageTool:
    """A coverage tool: the languages it measures, each granularity it can measure with how to ask for it, and
    `measures`, which reads a command that runs it (None for a command that does not)."""

    name: str
    languages: frozenset[str]
    can: Mapping[Granularity, str]
    measures: Measure


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageMeasured(Fact):
    """A coverage tool CI runs, in one job, and what it measures there for which languages."""

    job: str
    tool: str
    languages: frozenset[str]
    granularities: frozenset[Granularity]
    read: tuple[str, ...] = ()
    via: tuple[Origin, ...] = ()
    heuristic: bool = False


def built_in_coverage_tools() -> tuple[CoverageTool, ...]:
    """Every coverage tool defined by a module of the shared build systems, the shared tools or a profile."""
    from project_validator.components import built_in

    return built_in(CoverageTool)


def coverage_facts(facts: Facts, context: Context, tools: Iterable[CoverageTool]) -> Iterator[CoverageMeasured]:
    """What the coverage tools among `tools` measure in each command of `facts` that runs one."""
    tools = tuple(tools)
    for command in facts.of(Command):
        for tool in tools:
            measured = tool.measures(command, context)
            if measured is not None and measured.granularities:
                yield CoverageMeasured(
                    origin=command.origin,
                    job=command.job,
                    tool=tool.name,
                    languages=tool.languages,
                    granularities=measured.granularities,
                    read=measured.read,
                    via=command.via,
                    heuristic=measured.heuristic,
                )


def measured(*granularities: Granularity | None, read: Iterable[str] = (), heuristic: bool = False) -> Measurement:
    """A measurement of the `granularities` that are not None."""
    return Measurement(
        granularities=frozenset(found for found in granularities if found is not None),
        read=tuple(dict.fromkeys(read)),
        heuristic=heuristic,
    )


__all__ = [
    "CoverageMeasured",
    "CoverageTool",
    "Granularity",
    "Measure",
    "Measurement",
    "built_in_coverage_tools",
    "coverage_facts",
    "measured",
]
