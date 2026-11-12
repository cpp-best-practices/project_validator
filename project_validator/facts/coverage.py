"""The coverage aspect of tools (see `project_validator.facts.tools`): its levels are the granularities of coverage,
each at one of three rungs: measured (the counters are collected), reported (a report CI produces shows the numbers,
where a person or a service sees them) or gated (CI fails when they fall below a threshold).

Coverage tools are ordinary `Tool`s whose `can` holds a `coverage` aspect; their runs are `ToolRun`s that provide
it. `coverage_tool`, `measured` and `reported` only spell those for coverage: a granularity's level is its name
(`branch`: measured), `branch reported` or `branch gated`, each rung including the ones below.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Levels, Run, Tool, provided

COVERAGE = "coverage"


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


def coverage_tool(
    *,
    name: str,
    languages: frozenset[str],
    can: Mapping[Granularity, str],
    measures: Claim,
    reads: tuple[str, ...] = (),
) -> Tool:
    """A tool that measures coverage: `can` maps each granularity it measures to how to ask for it."""
    return Tool(
        name=name,
        languages=languages,
        can={COVERAGE: {str(granularity): how for granularity, how in can.items()}},
        claims=measures,
        reads=reads,
    )


class Rung(enum.StrEnum):
    """How far a run takes a granularity: measured, reported where it can be seen, or gated by a threshold."""

    MEASURED = "measured"
    REPORTED = "reported"
    GATED = "gated"

    @property
    def rank(self) -> int:
        return tuple(Rung).index(self)


def level(granularity: Granularity, rung: Rung) -> str:
    """The level of the coverage aspect that `granularity` at `rung` is: `branch`, `branch reported`, `branch gated`."""
    return str(granularity) if rung is Rung.MEASURED else f"{granularity} {rung}"


def rung_of(levels: Levels, granularity: Granularity) -> Rung | None:
    """The highest rung `levels` take `granularity` to; None when they do not measure it."""
    return next((rung for rung in reversed(Rung) if level(granularity, rung) in levels), None)


def measured(
    *granularities: Granularity | None,
    reported: Iterable[Granularity | None] = (),
    gated: Iterable[Granularity | None] = (),
    read: Iterable[Setting | str] = (),
    heuristic: bool = False,
) -> Run:
    """A run that measures the `granularities` that are not None, and takes those `reported` and `gated` further
    (a gated granularity is reported, a reported one measured)."""
    by_rung = {Rung.GATED: tuple(gated), Rung.REPORTED: tuple(reported), Rung.MEASURED: granularities}
    reached: list[str] = []
    for rung, found in by_rung.items():
        reached += [
            level(granularity, lower)
            for granularity in found
            if granularity
            for lower in Rung
            if lower.rank <= rung.rank
        ]
    return provided(COVERAGE, *reached, read=read, heuristic=heuristic)


def reported(
    *granularities: Granularity | None,
    gated: Iterable[Granularity | None] = (),
    read: Iterable[Setting | str] = (),
    heuristic: bool = False,
) -> Run:
    """A run that reports the `granularities` that are not None, and gates on those `gated`."""
    return measured(reported=granularities, gated=gated, read=read, heuristic=heuristic)


__all__ = ["COVERAGE", "Granularity", "Rung", "coverage_tool", "level", "measured", "reported", "rung_of"]
