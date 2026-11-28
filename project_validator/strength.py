"""A tool's strength (upstream #295): how much of it is left on, from 0 to 1, after what its configuration turns off
(`Disabled`) and the suppressions written in the code (`Suppressions`). The score counts a gate only when its
strongest tool is at least `COVERED` strong, and scales its extra credit by its tools' strength.

    strength = max(0, 1 - the weights of what is turned off - the density of the suppressions)

A diagnostic turned off weighs by its kind, its scope and whether a comment says why (`WEIGHTS`): turned off
everywhere, everything (`-*`, `ALL`, `-w`) leaves nothing; for one file, half. The suppressions in the code that turn
off rules that find bugs weigh by their density in the product's code of the tool's languages: `DENSITY` per
unjustified suppression per thousand lines (`JUSTIFIED_DENSITY` per justified one), at most `MOST_DENSITY`; those that
turn off only lint rules that find no bugs weigh nothing. Each rule's comments are held below `BELOW` times what
turning the rule off weighs, for their file and everywhere. A file turned off whole weighs as a blanket for one file.
The numbers are in `policy/strength.toml` (upstream #440)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from project_validator import policy_tables
from project_validator.facts import Facts
from project_validator.facts.structure import SourceFile
from project_validator.facts.suppressions import BLANKET, FILE, GLOBAL, KEY, Disabled, Suppressions, finding_bugs
from project_validator.facts.tools import known_tools

_TABLE = policy_tables.load("strength")  # its comments say why each number is what it is
# The strength a gate's strongest tool needs for the gate to count.
COVERED: float = _TABLE["covered"]
# (kind, scope, justified) -> weight; a global blanket leaves nothing, and a lint rule that finds no bugs nothing.
WEIGHTS: Mapping[tuple[str, str, bool], float] = {
    (kind, scope, justified): weights["justified" if justified else "unjustified"]
    for kind, scopes in _TABLE["weights"].items()
    for scope, weights in scopes.items()
    for justified in (False, True)
}
_DENSITY: Mapping[str, float] = _TABLE["density"]
DENSITY, JUSTIFIED_DENSITY, MOST_DENSITY, BELOW = (
    _DENSITY[name] for name in ("unjustified", "justified", "most", "below")
)


def _weights(facts: Facts) -> dict[str, float]:
    found: dict[str, float] = {}
    for disabled in facts.of(Disabled):
        found[disabled.tool] = (
            found.get(disabled.tool, 0.0) + WEIGHTS[disabled.kind, disabled.scope, disabled.justified]
        )
    return found


def _held(justified: list[bool], rule: str, scope: str, thousands: float) -> float:
    """What comments turning off `rule` weigh (each `justified` or not), held below turning it off in `scope`."""
    weighed = sum(JUSTIFIED_DENSITY if each else DENSITY for each in justified) / thousands
    return min(weighed, BELOW * WEIGHTS[BLANKET if rule == "*" else KEY, scope, all(justified)])


def _comments(facts: Facts) -> dict[tuple[str, str], dict[str, list[bool]]]:
    """Each (tool, rule that finds bugs) the code's comments turn off: in each file, whether each comment says why."""
    found: dict[tuple[str, str], dict[str, list[bool]]] = {}
    for suppressions in facts.of(Suppressions):
        for each in suppressions.found:
            for rule in finding_bugs(suppressions.tool, each.rules):
                files = found.setdefault((suppressions.tool, rule), {})
                files.setdefault(suppressions.origin.path, []).append(each.justified)
    return found


def _densities(facts: Facts) -> dict[str, float]:
    """Each tool's suppressions in the code, weighed by their density in its languages' product lines."""
    languages = {tool.name: tool.languages for tool in known_tools()}
    sources = [source for source in facts.of(SourceFile) if source.role == "product"]

    def thousands(tool: str) -> float:
        lines = sum(source.lines for source in sources if source.language in languages.get(tool, frozenset()))
        return max(lines, 1) / 1000

    weighed: dict[str, float] = {}
    for (tool, rule), files in _comments(facts).items():
        in_files = sum(_held(justified, rule, FILE, thousands(tool)) for justified in files.values())
        everywhere = BELOW * WEIGHTS[BLANKET if rule == "*" else KEY, GLOBAL, all(map(all, files.values()))]
        weighed[tool] = weighed.get(tool, 0.0) + min(in_files, everywhere)
    densities = {tool: min(MOST_DENSITY, weight) for tool, weight in weighed.items()}
    for suppressions in facts.of(Suppressions):
        if suppressions.blanket:
            tool = suppressions.tool
            densities[tool] = densities.get(tool, 0.0) + WEIGHTS[BLANKET, FILE, False]
    return densities


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnedOff:
    """A diagnostic that finds bugs, turned off for `tool` in the file at `path`, and what it weighs: turning it back
    on, and fixing what it finds, is a next step worth the strength it restores."""

    tool: str
    diagnostic: str
    path: str
    weight: float
    why: str = ""  # what the diagnostic guards against, where it is known


def turned_off(facts: Facts) -> tuple[TurnedOff, ...]:
    """What the tools' configuration turns off that finds bugs (blanket or key), the heaviest first."""
    found = (
        TurnedOff(
            tool=disabled.tool,
            diagnostic=disabled.diagnostic,
            path=disabled.origin.path,
            weight=WEIGHTS[disabled.kind, disabled.scope, disabled.justified],
            why=disabled.why,
        )
        for disabled in facts.of(Disabled)
        if disabled.kind in (BLANKET, KEY)
    )
    return tuple(sorted(found, key=lambda off: -off.weight))


def causes(facts: Facts) -> dict[str, tuple[float, float]]:
    """What weakens each tool something turns off: (what its configuration turns off, what the comments in the code
    do), each as the strength it takes."""
    weights, densities = _weights(facts), _densities(facts)
    return {tool: (weights.get(tool, 0.0), densities.get(tool, 0.0)) for tool in {*weights, *densities}}


def strengths(facts: Facts) -> dict[str, float]:
    """The strength of each tool something turns off (a tool nothing turns off is at full strength, 1)."""
    return {
        tool: round(max(0.0, 1.0 - configuration - comments), 6)
        for tool, (configuration, comments) in causes(facts).items()
    }


__all__ = [
    "BELOW",
    "COVERED",
    "DENSITY",
    "JUSTIFIED_DENSITY",
    "MOST_DENSITY",
    "WEIGHTS",
    "TurnedOff",
    "causes",
    "strengths",
    "turned_off",
]
