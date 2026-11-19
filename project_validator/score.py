"""The tooling score (upstream #295): three numbers read from the reports, beside the statuses, which do not change.

- **Level** is a gated tech tree: level N when the core and project cells of every check of levels 1 to N pass.
  Level 4 needs every applicable cell, auxiliary ones included.
- **Completeness** is covered cells over applicable cells, averaged across units (the whole project's own cells
  are one more unit). Auxiliary cells weigh half, a warning covers half a cell, a skip is not applicable, and an
  error scores nothing but stays in the maximum, so neither adding untooled code nor hiding something ever pays.
- **Depth** is the high score: each tool in a covered cell earns points by its rank in the cell, by tier. Depth
  earned in a level counts only once the levels below it are complete; the rest is shown as locked.

A **cell** is one check's result for one ecosystem in one unit (a place); a check of the whole project (no places)
is one project cell.

This is the preview (version 0): it reads only what the reports carry. Strength (disabled diagnostics, suppression
density), advisory runs at half points, tool families and verified points need facts the readers do not record yet,
and arrive with version 1. Until then a covered cell earns its first rank even when the check names no tool, so
checks that do not report their tools do not distort the comparison.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace

from project_validator.core import Status
from project_validator.runner import Report

SCORE_VERSION = "0"

# The checks each level's core and project cells must pass, in order; every other check belongs to level 4.
LEVELS: Mapping[int, tuple[str, ...]] = {
    1: (
        "ci-present",
        "compiler-warnings",
        "warnings-as-errors",
        "code-formatting",
        "tests-run",
        "license",
        "vcs-ignore",
    ),
    2: ("static-analysis", "type-checking", "coverage", "dependency-management", "dependency-audit"),
    3: ("sanitizers", "fuzz-testing", "mutation-testing", "security-scanning", "action-pinning"),
}
TOP_LEVEL = 4

CORE, AUXILIARY, PROJECT = "core", "auxiliary", "project"
_WEIGHT = {CORE: 1.0, AUXILIARY: 0.5, PROJECT: 1.0}
# Points for the 1st, 2nd, 3rd, ... tool in a cell; tools past the end earn nothing.
_RANKS = {CORE: (10, 5, 2, 1, 1, 1), AUXILIARY: (5, 2, 1), PROJECT: (10, 5, 2, 1, 1, 1)}
_FLAT = 5  # a project cell that passes without naming a tool (a licence, a security policy)
_COVERS = {Status.PASS: 1.0, Status.WARN: 0.5}


def level_of(check: str) -> int:
    return next((level for level, checks in LEVELS.items() if check in checks), TOP_LEVEL)


@dataclass(frozen=True, slots=True, kw_only=True)
class Cell:
    check: str
    level: int
    ecosystem: str  # "" for a project cell
    unit: str  # "" for a project cell
    tier: str
    status: Status
    tools: tuple[str, ...]
    points: float = 0.0
    counted: bool = False

    @property
    def covered(self) -> float:
        return _COVERS.get(self.status, 0.0)

    @property
    def weight(self) -> float:
        return _WEIGHT[self.tier]

    @property
    def first_rank(self) -> float:
        return _FLAT if self.tier == PROJECT and not self.tools else _RANKS[self.tier][0]

    def earned(self) -> float:
        """The cell's points before gating: its tools by rank (at least its first rank, named or not), scaled by
        how much of the cell is covered."""
        if not self.covered:
            return 0.0
        if self.tier == PROJECT and not self.tools:
            return _FLAT * self.covered
        ranks = _RANKS[self.tier]
        return sum(ranks[: max(1, len(self.tools))]) * self.covered

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "level": self.level,
            "ecosystem": self.ecosystem,
            "unit": self.unit,
            "tier": self.tier,
            "status": str(self.status),
            "tools": list(self.tools),
            "points": _number(self.points),
            "counted": self.counted,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Opportunity:
    """A cell that is not covered, and what covering it is worth."""

    check: str
    ecosystem: str
    unit: str
    tier: str
    status: Status
    level: int  # the level of its check
    completeness: float  # how much completeness would rise
    depth: float  # the first-rank points it would earn (0 while its level is locked)
    blocks: int | None  # the next level, when the cell stands in its way
    unlocks: int | None  # the next level, when the cell alone stands in its way

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "ecosystem": self.ecosystem,
            "unit": self.unit,
            "tier": self.tier,
            "status": str(self.status),
            "level": self.level,
            "completeness": round(self.completeness, 4),
            "depth": _number(self.depth),
            "blocks": self.blocks,
            "unlocks": self.unlocks,
        }

    def describe(self) -> str:
        unit = {"": "", ".": "the root"}.get(self.unit, f"unit {self.unit}")
        where = " in ".join(part for part in (self.ecosystem, unit) if part)
        gains = [f"+{self.completeness:.1%} completeness"]
        if self.depth:
            gains.append(f"+{_number(self.depth)} depth")
        if self.unlocks is not None:
            gains.append(f"unlocks Level {self.unlocks}")
        elif self.blocks is not None:
            gains.append(f"toward Level {self.blocks}")
        return f"{self.check}{f' ({where})' if where else ''}: {', '.join(gains)}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Score:
    level: int
    completeness: float
    depth: float
    locked_depth: float
    cells: tuple[Cell, ...]
    opportunities: tuple[Opportunity, ...]

    def summary(self) -> str:
        percent = math.floor(round(self.completeness * 100, 6))
        return f"Level {self.level} · {percent}% complete · {_number(self.depth)} depth"

    def as_dict(self) -> dict[str, object]:
        return {
            "version": SCORE_VERSION,
            "preview": True,
            "level": self.level,
            "completeness": round(self.completeness, 4),
            "depth": _number(self.depth),
            "locked_depth": _number(self.locked_depth),
            "cells": [cell.as_dict() for cell in self.cells],
            "opportunities": [opportunity.as_dict() for opportunity in self.opportunities],
        }


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def _report_cells(report: Report) -> Iterator[Cell]:
    """The report's applicable cells: one per place that does not skip, or one project cell for a check of the whole
    project."""
    name, level = report.check.name, level_of(report.check.name)
    if not report.result.places:
        if report.result.status is not Status.SKIP:
            yield Cell(
                check=name, level=level, ecosystem="", unit="", tier=PROJECT, status=report.result.status, tools=()
            )
        return
    for place in report.result.places:
        if place.result.status is not Status.SKIP:
            tier = AUXILIARY if place.auxiliary else CORE
            yield Cell(
                check=name,
                level=level,
                ecosystem=place.ecosystem,
                unit=place.unit,
                tier=tier,
                status=place.result.status,
                tools=place.tools,
            )


def _blocking(cells: Iterable[Cell], level: int) -> list[Cell]:
    """The cells that stand between the project and `level`: below the top level, the core and project cells of
    levels 1 to `level` that do not pass; at the top, every cell that does not."""
    return [
        cell
        for cell in cells
        if cell.status is not Status.PASS and (level == TOP_LEVEL or (cell.level <= level and cell.tier != AUXILIARY))
    ]


def _ran_all(level: int, ran: frozenset[str], every_check: frozenset[str]) -> bool:
    """Whether each check `level` needs ran (a skip counts as running): its own, or every check for the top."""
    return (every_check if level == TOP_LEVEL else frozenset(LEVELS[level])) <= ran


def _level(cells: Sequence[Cell], ran: frozenset[str], every_check: frozenset[str]) -> int:
    """The highest level reached: no cell blocks it or a level below, and each check they need ran."""
    reached = 0
    while reached < TOP_LEVEL and not _blocking(cells, reached + 1) and _ran_all(reached + 1, ran, every_check):
        reached += 1
    return reached


def _units(cells: Iterable[Cell]) -> dict[str, list[Cell]]:
    units: dict[str, list[Cell]] = defaultdict(list)
    for cell in cells:
        units[cell.unit].append(cell)
    return units


def _completeness(units: Mapping[str, Sequence[Cell]]) -> float:
    if not units:
        return 1.0
    return sum(
        sum(cell.weight * cell.covered for cell in cells) / sum(cell.weight for cell in cells)
        for cells in units.values()
    ) / len(units)


def _opportunity(cell: Cell, unit_weight: float, units: int, level: int, blocking: Sequence[Cell]) -> Opportunity:
    """What covering `cell` is worth, in a unit of `unit_weight` among `units`, at `level`."""
    missing = 1.0 - cell.covered
    return Opportunity(
        check=cell.check,
        ecosystem=cell.ecosystem,
        unit=cell.unit,
        tier=cell.tier,
        status=cell.status,
        level=cell.level,
        completeness=cell.weight * missing / unit_weight / units,
        depth=cell.first_rank * missing if cell.level <= level + 1 else 0.0,
        blocks=level + 1 if cell in blocking else None,
        unlocks=level + 1 if list(blocking) == [cell] else None,
    )


def _rank(opportunity: Opportunity) -> tuple[bool, bool, int, bool, float, float, str]:
    """The next level's blockers first (lowest level first), then core before auxiliary, then by what it is worth."""
    return (
        opportunity.blocks is None,
        opportunity.unlocks is None,
        opportunity.level,
        opportunity.tier == AUXILIARY,
        -opportunity.completeness,
        -opportunity.depth,
        opportunity.check,
    )


def _opportunities(
    cells: Sequence[Cell], units: Mapping[str, Sequence[Cell]], level: int, *, complete_run: bool
) -> tuple[Opportunity, ...]:
    """Every cell not covered, ranked. A cell unlocks the next level when it alone stands in the way; nothing does
    when the next level's checks did not all run."""
    blocking = _blocking(cells, level + 1) if level < TOP_LEVEL and complete_run else []
    weights = {unit: sum(cell.weight for cell in members) for unit, members in units.items()}
    found = (
        _opportunity(cell, weights[cell.unit], len(units), level, blocking)
        for cell in cells
        if cell.status is not Status.PASS
    )
    return tuple(sorted(found, key=_rank))


def score(reports: Iterable[Report], every_check: Iterable[str] = ()) -> Score:
    """The score of a run, from its reports. A level is reached only when each of its checks ran, and the top level
    only when `every_check` (the names of every check there is) ran too: a run narrowed by `--only` or `--skip`
    reaches no level past the checks it left out."""
    reports = list(reports)
    raw = [cell for report in reports for cell in _report_cells(report)]
    ran = frozenset(report.check.name for report in reports)
    everything = frozenset(every_check)
    level = _level(raw, ran, everything)
    cells = tuple(replace(cell, points=cell.earned(), counted=cell.level <= level + 1) for cell in raw)
    units = _units(cells)
    return Score(
        level=level,
        completeness=_completeness(units),
        depth=sum(cell.points for cell in cells if cell.counted),
        locked_depth=sum(cell.points for cell in cells if not cell.counted),
        cells=cells,
        opportunities=_opportunities(
            cells, units, level, complete_run=level == TOP_LEVEL or _ran_all(level + 1, ran, everything)
        ),
    )
