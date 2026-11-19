"""The tooling score (upstream #295), version 1: how many of the quality gates that apply to a project are in place.

**100% means every gate that applies to each part of the project is in place.** A part is a language in a unit (one
check's result there is a *slot*); the gates of the whole project (a licence, CI) are one slot each.

- **Fill.** A passing slot is filled, a warning half filled, anything else empty. A skip is not a slot (the gate does
  not apply), and an error stays one: hiding something never helps.
- **Weight.** Auxiliary code (`--auxiliary`) weighs half, and is not asked for the gates of the product alone
  (`NOT_FOR_AUXILIARY`: fuzzing tests, measuring their coverage, ...). Cosmetic checks (`UNSCORED`) are reported, not
  scored.
- **Pooled.** `percent = 100 * filled / slots`: a folder of data files with one gate weighs one slot.
- **Extra credit**, only for gates where more tools find more (`EXTRA_CREDIT`: analysers, scanners, auditors,
  fuzzers, sanitizers, type checkers): a second distinct tool in a slot earns a quarter slot more, a third a tenth;
  tools of one family (ruff and flake8; golangci-lint and the linters it bundles) count once. It is **held** until
  every slot is filled, so passing 100% always means every gate is in place.
- **Levels** are milestones: level N when the core and project slots of every check of levels 1 to N pass, and each
  of those checks ran; level 4, Complete, is 100% with every check run.

A next step is every slot not filled, with the points filling it is worth and the level it is needed for.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from project_validator.core import Status
from project_validator.runner import Report

SCORE_VERSION = "1"

# The checks each level's core and project slots must pass, in order; every other check belongs to the top level.
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
LEVEL_NAMES: Mapping[int, str] = {0: "Getting started", 1: "Foundations", 2: "Analysis", 3: "Hardening", 4: "Complete"}

# Reported, never scored: what a README shows is not a quality gate.
UNSCORED = frozenset({"status-badges"})
# The gates of the product alone, which auxiliary code (tests, examples, scripts) is not asked for.
NOT_FOR_AUXILIARY = frozenset(
    {
        "coverage",
        "fuzz-testing",
        "mutation-testing",
        "sanitizers",
        "hardening",
        "dependency-audit",
        "platform-matrix",
        "ci-build-types",
        "security-scanning",
    }
)
# The gates where each more tool finds more: two analysers are stronger than one; two formatters are not.
EXTRA_CREDIT = frozenset(
    {
        "static-analysis",
        "security-scanning",
        "dependency-audit",
        "fuzz-testing",
        "sanitizers",
        "type-checking",
        "compiler-warnings",
    }
)
# The extra credit of the 2nd, 3rd, ... distinct tool family in a slot, in slots.
EXTRA = (0.25, 0.10)
# Tools that are one tool for the extra credit: reimplementations of each other's rules.
FAMILIES: Mapping[str, str] = {"flake8": "ruff", "pylint": "pylint", "ruff": "ruff"}

CORE, AUXILIARY, PROJECT = "core", "auxiliary", "project"
_WEIGHT = {CORE: 1.0, AUXILIARY: 0.5, PROJECT: 1.0}
_FILLS = {Status.PASS: 1.0, Status.WARN: 0.5}


def level_of(check: str) -> int:
    return next((level for level, checks in LEVELS.items() if check in checks), TOP_LEVEL)


def family(tool: str) -> str:
    """The family a tool counts in for the extra credit: a bundled linter's bundle (`golangci-lint's gosec`), a
    reimplementation's original, else the tool itself."""
    bundle, separator, _ = tool.partition("'s ")
    return bundle if separator else FAMILIES.get(tool, tool)


@dataclass(frozen=True, slots=True, kw_only=True)
class Cell:
    """One slot: a check's result for a language in a unit (or for the whole project)."""

    check: str
    level: int
    ecosystem: str  # "" for the whole project
    unit: str  # "" for the whole project
    tier: str
    status: Status
    tools: tuple[str, ...]
    message: str = ""
    hint: str = ""

    @property
    def weight(self) -> float:
        return _WEIGHT[self.tier]

    @property
    def fill(self) -> float:
        return _FILLS.get(self.status, 0.0)

    @property
    def filled(self) -> float:
        return self.weight * self.fill

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(family(tool) for tool in self.tools))

    @property
    def extra(self) -> float:
        """The extra credit the slot earns, in slots: for each distinct tool family past the first, in a gate where
        more tools find more."""
        if self.check not in EXTRA_CREDIT or not self.fill:
            return 0.0
        return sum(EXTRA[: max(0, len(self.families) - 1)]) * self.weight * self.fill

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "level": self.level,
            "ecosystem": self.ecosystem,
            "unit": self.unit,
            "tier": self.tier,
            "status": str(self.status),
            "tools": list(self.tools),
            "weight": self.weight,
            "filled": self.filled,
            "extra": _number(self.extra),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NextStep:
    """A slot not filled, and what filling it is worth."""

    check: str
    ecosystem: str
    unit: str
    tier: str
    status: Status
    level: int  # the level of its check
    points: float  # how much the percent rises
    needed_for: int | None  # the next level, when the slot stands in its way
    completes: bool  # whether it alone stands in the way of the next level
    message: str = ""
    hint: str = ""

    @property
    def where(self) -> str:
        unit = {"": "", ".": ""}.get(self.unit, self.unit)
        return " in ".join(part for part in (self.ecosystem, unit) if part)

    def describe(self) -> str:
        """`coverage (C++ in lib): +12 points, needed for Level 2 (Analysis); run gcovr in CI`."""
        where = f" ({self.where})" if self.where else ""
        gains = [f"+{_points(self.points)} points"]
        if self.needed_for is not None:
            verb = "completes" if self.completes else "needed for"
            gains.append(f"{verb} Level {self.needed_for} ({LEVEL_NAMES[self.needed_for]})")
        hint = f"; {self.hint}" if self.hint else ""
        return f"{self.check}{where}: {', '.join(gains)}{hint}"

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "ecosystem": self.ecosystem,
            "unit": self.unit,
            "tier": self.tier,
            "status": str(self.status),
            "level": self.level,
            "points": round(self.points, 2),
            "needed_for": self.needed_for,
            "completes": self.completes,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Score:
    level: int
    filled: float
    slots: float
    extra_slots: float
    cells: tuple[Cell, ...]
    next_steps: tuple[NextStep, ...] = field(default=())

    @property
    def base(self) -> float:
        """The share of the slots filled, in percent."""
        return 100.0 * self.filled / self.slots if self.slots else 100.0

    @property
    def complete(self) -> bool:
        return math.isclose(self.filled, self.slots)

    @property
    def extra(self) -> float:
        """The extra credit, in percent: counted once every slot is filled."""
        return 100.0 * self.extra_slots / self.slots if self.slots and self.complete else 0.0

    @property
    def held(self) -> float:
        """The extra credit earned but held until every slot is filled, in percent."""
        return 100.0 * self.extra_slots / self.slots if self.slots and not self.complete else 0.0

    @property
    def percent(self) -> float:
        return 100.0 + self.extra if self.complete else self.base

    @property
    def gates(self) -> int:
        return sum(1 for cell in self.cells if cell.fill)

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES[self.level]

    def summary(self) -> str:
        """`87% · Level 1 Foundations · 41 of 47 gates in place`."""
        head = f"{_floor(self.percent)}% · Level {self.level} {self.level_name}"
        if self.complete:
            gates = f"all {len(self.cells)} gates in place"
            return f"{head} · {gates}, +{_floor(self.extra)} extra credit" if self.extra else f"{head} · {gates}"
        gates = f"{self.gates} of {len(self.cells)} gates in place"
        held = f" (+{_floor(self.held)} extra credit held until every gate is in place)" if self.held else ""
        return f"{head} · {gates}{held}"

    def breakdown(self) -> dict[str, tuple[float, float]]:
        """Language -> (filled, slots); the whole project's own gates are under ""."""
        found: dict[str, tuple[float, float]] = {}
        for cell in self.cells:
            filled, slots = found.get(cell.ecosystem, (0.0, 0.0))
            found[cell.ecosystem] = (filled + cell.filled, slots + cell.weight)
        return found

    def as_dict(self) -> dict[str, object]:
        return {
            "version": SCORE_VERSION,
            "percent": round(self.percent, 2),
            "base": round(self.base, 2),
            "extra": round(self.extra, 2),
            "held": round(self.held, 2),
            "level": self.level,
            "level_name": self.level_name,
            "filled": _number(self.filled),
            "slots": _number(self.slots),
            "summary": self.summary(),
            "breakdown": {name: [_number(a), _number(b)] for name, (a, b) in self.breakdown().items()},
            "cells": [cell.as_dict() for cell in self.cells],
            "next_steps": [step.as_dict() for step in self.next_steps],
        }


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def _floor(value: float) -> int:
    return math.floor(round(value, 6))


def _points(value: float) -> str:
    return str(_number(round(value, 1)))


def _hint(details: Sequence[str]) -> str:
    return details[0] if details else ""


def _report_cells(report: Report) -> Iterator[Cell]:
    """The report's slots: one per place that does not skip, or one for a check of the whole project; auxiliary
    places of the product's own gates, and unscored checks, are left out."""
    name, level = report.check.name, level_of(report.check.name)
    if name in UNSCORED:
        return
    result = report.result
    if not result.places:
        if result.status is not Status.SKIP:
            yield Cell(
                check=name,
                level=level,
                ecosystem="",
                unit="",
                tier=PROJECT,
                status=result.status,
                tools=(),
                message=result.message,
                hint=_hint(result.details),
            )
        return
    for place in result.places:
        tier = AUXILIARY if place.auxiliary else CORE
        if place.result.status is Status.SKIP or (tier == AUXILIARY and name in NOT_FOR_AUXILIARY):
            continue
        yield Cell(
            check=name,
            level=level,
            ecosystem=place.ecosystem,
            unit=place.unit,
            tier=tier,
            status=place.result.status,
            tools=place.tools,
            message=place.result.message,
            hint=_hint(place.result.details),
        )


def _blocking(cells: Iterable[Cell], level: int) -> list[Cell]:
    """The slots that stand between the project and `level`: below the top level, the core and project slots of
    levels 1 to `level` that do not pass; at the top, every slot that does not."""
    return [
        cell
        for cell in cells
        if cell.status is not Status.PASS and (level == TOP_LEVEL or (cell.level <= level and cell.tier != AUXILIARY))
    ]


def _ran_all(level: int, ran: frozenset[str], every_check: frozenset[str]) -> bool:
    """Whether each check `level` needs ran (a skip counts as running): its own, or every check for the top."""
    return (every_check if level == TOP_LEVEL else frozenset(LEVELS[level])) <= ran


def _level(cells: Sequence[Cell], ran: frozenset[str], every_check: frozenset[str]) -> int:
    reached = 0
    while reached < TOP_LEVEL and not _blocking(cells, reached + 1) and _ran_all(reached + 1, ran, every_check):
        reached += 1
    return reached


def _rank(step: NextStep) -> tuple[bool, bool, int, bool, float, str]:
    """The next level's blockers first (the one that completes it first), lowest level first, then core before
    auxiliary, then by the points."""
    return (step.needed_for is None, not step.completes, step.level, step.tier == AUXILIARY, -step.points, step.check)


def _next_steps(cells: Sequence[Cell], slots: float, level: int, *, complete_run: bool) -> tuple[NextStep, ...]:
    blocking = _blocking(cells, level + 1) if level < TOP_LEVEL and complete_run else []
    steps = (
        NextStep(
            check=cell.check,
            ecosystem=cell.ecosystem,
            unit=cell.unit,
            tier=cell.tier,
            status=cell.status,
            level=cell.level,
            points=100.0 * (cell.weight - cell.filled) / slots,
            needed_for=level + 1 if cell in blocking else None,
            completes=blocking == [cell],
            message=cell.message,
            hint=cell.hint,
        )
        for cell in cells
        if cell.status is not Status.PASS
    )
    return tuple(sorted(steps, key=_rank))


def score(reports: Iterable[Report], every_check: Iterable[str] = ()) -> Score:
    """The score of a run, from its reports. A level is reached only when each of its checks ran, and the top level
    only when `every_check` (the names of every check there is) ran too: a run narrowed by `--only` or `--skip`
    reaches no level past the checks it left out."""
    reports = list(reports)
    cells = tuple(cell for report in reports for cell in _report_cells(report))
    ran = frozenset(report.check.name for report in reports)
    everything = frozenset(every_check)
    level = _level(cells, ran, everything)
    slots = sum(cell.weight for cell in cells)
    complete_run = level == TOP_LEVEL or _ran_all(level + 1, ran, everything)
    return Score(
        level=level,
        filled=sum(cell.filled for cell in cells),
        slots=slots,
        extra_slots=sum(cell.extra for cell in cells),
        cells=cells,
        next_steps=_next_steps(cells, slots, level, complete_run=complete_run),
    )


__all__ = [
    "EXTRA_CREDIT",
    "LEVELS",
    "LEVEL_NAMES",
    "NOT_FOR_AUXILIARY",
    "SCORE_VERSION",
    "TOP_LEVEL",
    "UNSCORED",
    "Cell",
    "NextStep",
    "Score",
    "family",
    "level_of",
    "score",
]
