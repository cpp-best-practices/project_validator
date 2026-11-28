"""The tooling score (upstream #295), version 1: how many of the quality gates that apply to a project are in place.

**100% means every gate that applies to each part of the project is in place.** A part is a language in a unit (one
check's result there is a *slot*); the gates of the whole project (a licence, CI) are one slot each.

- **Fill.** A passing slot is filled, a warning half filled, anything else empty. A skip is not a slot (the gate does
  not apply), and an error stays one: hiding something never helps. A slot whose tools reach only part of the
  product's code (`Result.share`, upstream #333) is filled by the share of its lines they reach.
- **Weight.** A language's core slots weigh its share of its unit's product lines (`sizes`), at least `FLOOR`
  (upstream #331); the levels still ask every language for every gate. Auxiliary code (`--auxiliary`) weighs half,
  and is not asked for the gates of the product alone
  (`NOT_FOR_AUXILIARY`: fuzzing tests, measuring their coverage, ...). Cosmetic checks (`COSMETIC`) are reported, not
  scored. The defects the validator finds itself (`FINDINGS`) only take points away: only the processes a project
  puts in place earn them.
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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath

from project_validator import policy_tables
from project_validator.core import Result, Status
from project_validator.facts import Facts
from project_validator.judging import NOT_FOR_AUXILIARY
from project_validator.runner import Report
from project_validator.strength import COVERED, TurnedOff

# 2: each language's slots weigh its share of its unit's code (upstream #331).
# 3: what the validator finds itself (`FINDINGS`) earns nothing; 4: tools' strength weighs their slots.
# 5: style disables cost nothing; 6: ruff's linter and flake8 are one family, as `FAMILIES` meant (upstream #440).
# 7: a comment turning off lint rules that find no bugs costs nothing, each rule's comments are held below turning the
# rule off, and a slot is filled as far as its strongest tool is strong (upstream #295).
SCORE_VERSION = "7"
# The digest of the scored policy files (`policy_tables.SCORED`) this version stands for: a test fails when they change
# without a new SCORE_VERSION, and gives the new digest to put here.
POLICY_DIGEST = "1fd7740ce1a59f78"

# The tables are policy, with the comments that say why: policy/score.toml (upstream #440).
_TABLE = policy_tables.load("score")
# The checks each level's core and project slots must pass, in order; every other check belongs to the top level.
LEVELS: Mapping[int, tuple[str, ...]] = {int(level): tuple(checks) for level, checks in _TABLE["levels"].items()}
TOP_LEVEL = max(LEVELS) + 1
LEVEL_NAMES: Mapping[int, str] = {int(level): name for level, name in _TABLE["level_names"].items()}

# Reported, never scored.
COSMETIC = frozenset(_TABLE["unscored"]["cosmetic"])
# Defects the validator finds itself: they can take points away but never add them.
FINDINGS = frozenset(_TABLE["unscored"]["findings"])
# The checks that never earn points: the cosmetic ones are not scored at all.
UNSCORED = COSMETIC | FINDINGS
# The gates where each more tool finds more, and the extra credit of the 2nd, 3rd, ... distinct tool family in a slot.
EXTRA_CREDIT = frozenset(_TABLE["extra_credit"]["checks"])
EXTRA: tuple[float, ...] = tuple(_TABLE["extra_credit"]["steps"])
# Tools that are one tool for the extra credit: reimplementations of each other's rules.
FAMILIES: Mapping[str, str] = dict(_TABLE["families"])

CORE, AUXILIARY, PROJECT = "core", "auxiliary", "project"
_WEIGHT: Mapping[str, float] = dict(_TABLE["tiers"])
# The least a language's core slots weigh, whatever its share of the code: a gap in a small language still costs.
FLOOR: float = _TABLE["weights"]["floor"]

# Each language's (an ecosystem's, by its label) share of its unit's product lines: (label, unit) -> share.
type Sizes = Mapping[tuple[str, str], float]
_FILLS = {Status.PASS: 1.0, Status.WARN: 0.5}


def weight_of(tier: str) -> float:
    """What a slot of `tier` (`CORE`, `AUXILIARY`, `PROJECT`) weighs, before its language's share."""
    return _WEIGHT[tier]


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
    # The share of the gate's code its tools reach (see `Result.share`), which fills a passing slot that far.
    share: float = 1.0
    # The language's share of its unit's product lines (see `sizes`), which a core slot weighs, at least `FLOOR`.
    size: float = 1.0
    # Each of its tools' strength (see `project_validator.strength`), in the order of `tools`: none when nothing weakens
    # them.
    strengths: tuple[float, ...] = ()

    @property
    def strength(self) -> float:
        """Its strongest tool's strength: the slot is filled only when it is at least `COVERED`."""
        return max(self.strengths, default=1.0)

    @property
    def passes(self) -> bool:
        """Whether the gate is in place: it passes, and its strongest tool is strong enough (see `COVERED`)."""
        return self.status is Status.PASS and self.strength >= COVERED

    @property
    def power(self) -> float:
        """Its tools' mean strength, by which its extra credit is scaled."""
        return sum(self.strengths) / len(self.strengths) if self.strengths else 1.0

    @property
    def weight(self) -> float:
        return weight_of(self.tier) * (max(FLOOR, self.size) if self.tier == CORE else 1.0)

    @property
    def reach(self) -> float:
        """How far the gate is in place, before its tools' strength: a finding's (`FINDINGS`) slot, there only when it
        found a defect, never; nor one whose strongest tool is turned off more than half (see `COVERED`)."""
        if self.check in FINDINGS or self.strength < COVERED:
            return 0.0
        return _FILLS.get(self.status, 0.0) * self.share

    @property
    def fill(self) -> float:
        """How much of the slot is filled: as far as the gate is in place, and as far as its strongest tool is strong,
        so that whatever turns a tool off shows in the score."""
        return self.reach * self.strength

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
        if self.check not in EXTRA_CREDIT or not self.reach:
            return 0.0
        return sum(EXTRA[: max(0, len(self.families) - 1)]) * self.weight * self.reach * self.power

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
            "strength": _number(self.strength),
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
        head = f"{floor_percent(self.percent)}% · Level {self.level} {self.level_name}"
        if self.complete:
            gates = f"all {len(self.cells)} gates in place"
            return f"{head} · {gates}, +{_credit(self.extra)} extra credit" if self.extra else f"{head} · {gates}"
        gates = f"{self.gates} of {len(self.cells)} gates in place"
        held = f" (+{_credit(self.held)} extra credit held until every gate is in place)" if self.held else ""
        return f"{head} · {gates}{held}"

    def _tally(self, key: Callable[[Cell], str]) -> dict[str, tuple[float, float]]:
        """`key` of each slot -> (filled, slots)."""
        found: dict[str, tuple[float, float]] = {}
        for cell in self.cells:
            filled, slots = found.get(key(cell), (0.0, 0.0))
            found[key(cell)] = (filled + cell.filled, slots + cell.weight)
        return found

    def breakdown(self) -> dict[str, tuple[float, float]]:
        """Language -> (filled, slots); the whole project's own gates are under ""."""
        return self._tally(lambda cell: cell.ecosystem)

    def units(self) -> dict[str, tuple[float, float]]:
        """Unit -> (filled, slots), for a project of several (upstream #295); the whole project's own gates are under
        ""."""
        return self._tally(lambda cell: cell.unit)

    @property
    def several_units(self) -> bool:
        return len({cell.unit for cell in self.cells} - {""}) > 1

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
            "units": {name: [_number(a), _number(b)] for name, (a, b) in self.units().items()},
            "cells": [cell.as_dict() for cell in self.cells],
            "next_steps": [step.as_dict() for step in self.next_steps],
        }


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def floor_percent(value: float) -> int:
    """A percent as the score shows it: whole points, rounded down (99.9999999 is 100)."""
    return math.floor(round(value, 6))


def _credit(value: float) -> str:
    """Extra credit, in percent: a tenth below one point, whole points above."""
    return f"{value:.1f}" if value < 1 else str(floor_percent(value))


def _points(value: float) -> str:
    return str(_number(round(value, 1)))


# The first words of a detail that says what to do, rather than what was found (a file, a job).
_ADVICE = frozenset(
    {"consider", "add", "remove", "commit", "run", "set", "enable", "pin", "fetch", "compare", "condition", "use"}
)


def _hint(details: Sequence[str]) -> str:
    """The first detail that says what to do (`consider running gcovr in CI`), else ""."""
    for detail in details:
        words = detail.split(maxsplit=1)
        if words and words[0].lower() in _ADVICE:
            return detail
    return ""


def sizes(facts: Facts) -> dict[tuple[str, str], float]:
    """Each ecosystem's share of the product lines of each unit it is in (its languages' and formats' together), by
    the source files' lines; test, tooling, example and vendored code count for none."""
    from project_validator.ecosystems import registered
    from project_validator.facts.structure import SourceFile, Unit
    from project_validator.facts.tools import owner

    units = tuple(found.directory for found in facts.of(Unit)) or (".",)
    labels = {language: ecosystem.label for ecosystem in registered() for language in ecosystem.languages}
    lines: dict[tuple[str, str], int] = {}
    totals: dict[str, int] = {}
    for source in facts.of(SourceFile):
        if source.role != "product" or source.language not in labels:
            continue
        unit = owner(str(PurePosixPath(source.path).parent), units)
        key = (labels[source.language], unit)
        lines[key] = lines.get(key, 0) + source.lines
        totals[unit] = totals.get(unit, 0) + source.lines
    return {key: count / totals[key[1]] for key, count in lines.items() if totals[key[1]]}


def _report_cells(report: Report, sizes_: Sizes) -> Iterator[Cell]:
    """The report's slots: one per place that does not skip, or one for a check of the whole project; auxiliary
    places of the product's own gates, and unscored checks, are left out."""
    name, level = report.check.name, level_of(report.check.name)
    if name in COSMETIC or (name in FINDINGS and report.result.status is Status.PASS):
        return
    result = report.result
    if not result.places:
        if result.status is not Status.SKIP:
            yield _cell(name, level, "", "", PROJECT, result, ())
        return
    for place in result.places:
        tier = AUXILIARY if place.auxiliary else CORE
        if place.result.status is Status.SKIP or (tier == AUXILIARY and name in NOT_FOR_AUXILIARY):
            continue
        if name in FINDINGS and place.result.status is Status.PASS:
            continue  # no defect found here: nothing to take away
        cell = _cell(name, level, place.ecosystem, place.unit, tier, place.result, place.tools)
        yield replace(cell, size=sizes_.get((place.ecosystem, place.unit), 1.0))


def _cell(check: str, level: int, ecosystem: str, unit: str, tier: str, result: Result, tools: tuple[str, ...]) -> Cell:
    return Cell(
        check=check,
        level=level,
        ecosystem=ecosystem,
        unit=unit,
        tier=tier,
        status=result.status,
        tools=tools,
        message=result.message,
        hint=_hint(result.details),
        share=result.share,
    )


def _blocking(cells: Iterable[Cell], level: int) -> list[Cell]:
    """The slots that stand between the project and `level`: below the top level, the core and project slots of
    levels 1 to `level` that do not pass; at the top, every slot that does not."""
    return [
        cell
        for cell in cells
        if not cell.passes and (level == TOP_LEVEL or (cell.level <= level and cell.tier != AUXILIARY))
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


_WEAKENED = "its tools are turned off more than half (strength {strength:.2f})"
_WEAKENED_HINT = "turn back on what their configuration and the code's suppressions turn off, and fix what they find"


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
            message=cell.message if cell.status is not Status.PASS else _WEAKENED.format(strength=cell.strength),
            hint=cell.hint if cell.status is not Status.PASS else _WEAKENED_HINT,
        )
        for cell in cells
        if not cell.passes
    )
    return tuple(sorted(steps, key=_rank))


def _weighed(cells: Iterable[Cell], strengths: Mapping[str, float]) -> tuple[Cell, ...]:
    """The cells, each with its tools' `strengths` (a tool not given is at full strength)."""
    return tuple(
        replace(cell, strengths=tuple(strengths.get(tool, 1.0) for tool in cell.tools))
        if any(tool in strengths for tool in cell.tools)
        else cell
        for cell in cells
    )


# The fewest points a re-enabling step must be worth to be shown.
SMALLEST_STEP: float = _TABLE["next_steps"]["smallest_step"]


def _restored(cell: Cell, off: TurnedOff) -> Cell:
    """`cell` with what `off` turns off of its tool turned back on."""
    found = cell.strengths or (1.0,) * len(cell.tools)
    strengths = (
        min(1.0, strength + off.weight) if tool == off.tool else strength
        for tool, strength in zip(cell.tools, found, strict=True)
    )
    return replace(cell, strengths=tuple(strengths))


def _reenabled(cells: Sequence[Cell], slots: float, turned: Iterable[TurnedOff]) -> Iterator[NextStep]:
    """A next step for each diagnostic that finds bugs a tool's configuration turns off, where turning it back on
    restores points: the slots of the tool's gates filled again, or their extra credit."""
    for off in turned:
        found = [cell for cell in cells if off.tool in cell.tools and cell.status is Status.PASS]
        restored = (_restored(cell, off) for cell in found)
        gained = sum(new.filled + new.extra - old.filled - old.extra for old, new in zip(found, restored, strict=True))
        points = 100.0 * gained / slots
        if points >= SMALLEST_STEP:
            yield NextStep(
                check=found[0].check,
                ecosystem=found[0].ecosystem,
                unit=found[0].unit,
                tier=found[0].tier,
                status=found[0].status,
                level=found[0].level,
                points=points,
                needed_for=None,
                completes=False,
                message=f"re-enable {off.diagnostic} in {off.path} ({off.tool})",
                hint=f"re-enable {off.diagnostic} in {off.path} and fix what {off.tool} finds"
                + (f"; {off.why}" if off.why else ""),
            )


def score(
    reports: Iterable[Report],
    every_check: Iterable[str] = (),
    sizes: Sizes | None = None,
    strengths: Mapping[str, float] | None = None,
    turned_off: Iterable[TurnedOff] = (),
) -> Score:
    """The score of a run, from its reports. A level is reached only when each of its checks ran, and the top level
    only when `every_check` (the names of every check there is) ran too: a run narrowed by `--only` or `--skip`
    reaches no level past the checks it left out. Each language's core slots weigh its `sizes` share (see `sizes`),
    at least `FLOOR`; a language with no share given weighs in full. Each tool's `strengths` (see
    `project_validator.strength`) weigh the slots it fills: a tool not given is at full strength."""
    reports = list(reports)
    cells = _weighed((cell for report in reports for cell in _report_cells(report, sizes or {})), strengths or {})
    ran = frozenset(report.check.name for report in reports)
    everything = frozenset(every_check)
    level = _level(cells, ran, everything)
    slots = sum(cell.weight for cell in cells)
    complete_run = level == TOP_LEVEL or _ran_all(level + 1, ran, everything)
    steps = _next_steps(cells, slots, level, complete_run=complete_run)
    return Score(
        level=level,
        filled=sum(cell.filled for cell in cells),
        slots=slots,
        extra_slots=sum(cell.extra for cell in cells),
        cells=cells,
        next_steps=tuple(sorted((*steps, *_reenabled(cells, slots, turned_off)), key=_rank)),
    )


def shortfalls(found: Score, *, min_level: int | None = None, min_completeness: float | None = None) -> list[str]:
    """How the score falls short of the floors `--min-level` and `--min-completeness` set (none when it meets them, or
    none is set). Completeness is the share of the gates in place: extra credit is no completeness."""
    short = []
    if min_level is not None and found.level < min_level:
        short.append(f"Level {found.level} {found.level_name} is below --min-level {min_level}")
    if min_completeness is not None and found.base < min_completeness:
        short.append(
            f"{_number(found.base)}% of the gates in place is below --min-completeness {_number(min_completeness)}"
        )
    return short


__all__ = [
    "COSMETIC",
    "EXTRA",
    "EXTRA_CREDIT",
    "FAMILIES",
    "FINDINGS",
    "FLOOR",
    "LEVELS",
    "LEVEL_NAMES",
    "NOT_FOR_AUXILIARY",
    "POLICY_DIGEST",
    "SCORE_VERSION",
    "SMALLEST_STEP",
    "TOP_LEVEL",
    "UNSCORED",
    "Cell",
    "NextStep",
    "Score",
    "family",
    "floor_percent",
    "level_of",
    "score",
    "shortfalls",
    "sizes",
    "weight_of",
]
