"""A tool's strength (upstream #295): how much of it is left on, from 0 to 1, after what its configuration turns off
(`Disabled`) and the suppressions written in the code (`Suppressions`). The score counts a gate only when its
strongest tool is at least `COVERED` strong, and scales its extra credit by its tools' strength.

    strength = max(0, 1 - the weights of what is turned off - the density of the suppressions)

A diagnostic turned off weighs by its kind, its scope and whether a comment says why (`WEIGHTS`): turned off
everywhere, everything (`-*`, `ALL`, `-w`) leaves nothing; for one file, half. The suppressions in the code weigh by
their density in the product's code of the tool's languages: `DENSITY` per unjustified suppression per thousand lines
(`JUSTIFIED_DENSITY` per justified one), at most `MOST_DENSITY`; a file turned off whole weighs as a blanket for one
file."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from project_validator.facts import Facts
from project_validator.facts.structure import SourceFile
from project_validator.facts.suppressions import BLANKET, FILE, GLOBAL, KEY, STYLISTIC, Disabled, Suppressions
from project_validator.facts.tools import known_tools

# The strength a gate's strongest tool needs for the gate to count.
COVERED = 0.5
# (kind, scope, justified) -> weight; a global blanket leaves nothing.
WEIGHTS: Mapping[tuple[str, str, bool], float] = {
    (BLANKET, GLOBAL, False): 1.0,
    (BLANKET, GLOBAL, True): 1.0,
    (BLANKET, FILE, False): 0.5,
    (BLANKET, FILE, True): 0.5,
    (KEY, GLOBAL, False): 0.25,
    (KEY, GLOBAL, True): 0.12,
    (KEY, FILE, False): 0.05,
    (KEY, FILE, True): 0.02,
    (STYLISTIC, GLOBAL, False): 0.02,
    (STYLISTIC, GLOBAL, True): 0.02,
    (STYLISTIC, FILE, False): 0.0,
    (STYLISTIC, FILE, True): 0.0,
}
DENSITY, JUSTIFIED_DENSITY, MOST_DENSITY = 0.02, 0.005, 0.5


def _weights(facts: Facts) -> dict[str, float]:
    found: dict[str, float] = {}
    for disabled in facts.of(Disabled):
        found[disabled.tool] = (
            found.get(disabled.tool, 0.0) + WEIGHTS[disabled.kind, disabled.scope, disabled.justified]
        )
    return found


def _densities(facts: Facts) -> dict[str, float]:
    """Each tool's suppressions in the code, weighed by their density in its languages' product lines."""
    languages = {tool.name: tool.languages for tool in known_tools()}
    sources = [source for source in facts.of(SourceFile) if source.role == "product"]
    counted: dict[str, tuple[float, float]] = {}
    for found in facts.of(Suppressions):
        unjustified, blankets = counted.get(found.tool, (0.0, 0.0))
        weighed = DENSITY * (found.count - found.justified) + JUSTIFIED_DENSITY * found.justified
        counted[found.tool] = (unjustified + weighed, blankets + WEIGHTS[BLANKET, FILE, False] * found.blanket)
    densities: dict[str, float] = {}
    for tool, (weighed, blankets) in counted.items():
        lines = sum(source.lines for source in sources if source.language in languages.get(tool, frozenset()))
        thousands = max(lines, 1) / 1000
        densities[tool] = min(MOST_DENSITY, weighed / thousands) + blankets
    return densities


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnedOff:
    """A diagnostic that finds bugs, turned off for `tool` in the file at `path`, and what it weighs: turning it back
    on, and fixing what it finds, is a next step worth the strength it restores."""

    tool: str
    diagnostic: str
    path: str
    weight: float


def turned_off(facts: Facts) -> tuple[TurnedOff, ...]:
    """What the tools' configuration turns off that finds bugs (blanket or key), the heaviest first."""
    found = (
        TurnedOff(
            tool=disabled.tool,
            diagnostic=disabled.diagnostic,
            path=disabled.origin.path,
            weight=WEIGHTS[disabled.kind, disabled.scope, disabled.justified],
        )
        for disabled in facts.of(Disabled)
        if disabled.kind in (BLANKET, KEY)
    )
    return tuple(sorted(found, key=lambda off: -off.weight))


def strengths(facts: Facts) -> dict[str, float]:
    """The strength of each tool something turns off (a tool nothing turns off is at full strength, 1)."""
    weights, densities = _weights(facts), _densities(facts)
    return {
        tool: round(max(0.0, 1.0 - weights.get(tool, 0.0) - densities.get(tool, 0.0)), 6)
        for tool in {*weights, *densities}
    }


__all__ = ["COVERED", "DENSITY", "JUSTIFIED_DENSITY", "MOST_DENSITY", "WEIGHTS", "TurnedOff", "strengths", "turned_off"]
