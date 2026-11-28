"""Where a score loses its points (upstream #295): what each slot lacks, split by cause, the heaviest first. The next
steps say what would add points; this says what is costing them, so a project knows what to correct: a gate that
fails, an answer the validator could not read, a step that can't fail CI, a tool that reaches part of the code, or
rules turned off in a tool's configuration or by comments in the code."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator.score import Cell, Score, where
from project_validator.words import counted

# Each cause: what it is, and what corrects it.
CAUSES: dict[str, tuple[str, str]] = {
    "failing": ("Gates that fail", "put the gate in place in CI (each is a next step)"),
    "unknown": (
        "Gates whose answer is not known",
        "make what CI runs readable (each check's details say what could not be read), or pass --fetch-remote",
    ),
    "warning": (
        "Gates in place but not enforced",
        "let the step fail CI: no `|| true`, `continue-on-error` or pipe without pipefail, and warnings as errors",
    ),
    "reach": ("Tools that reach only part of the code", "point the tools at all of the product's code"),
    "turned-off": (
        "Tools weakened by what is turned off",
        "turn the rules that find bugs back on, in the configuration and in comments, and fix what they find; "
        "code that needs a rule off belongs in one small, well-tested place",
    ),
    "found": ("Defects the validator found", "fix what the check reports"),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Lost:
    """What one slot loses to a cause, in points of the percent."""

    check: str
    ecosystem: str
    unit: str
    points: float
    detail: str = ""

    @property
    def where(self) -> str:
        return where(self.ecosystem, self.unit)

    def describe(self) -> str:
        """`static-analysis (C++): 4.2 points; clang-tidy at 0.7: …`."""
        place = f" ({self.where})" if self.where else ""
        detail = f"; {self.detail}" if self.detail else ""
        return f"{self.check}{place}: {in_points(self.points)} points{detail}"

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "ecosystem": self.ecosystem,
            "unit": self.unit,
            "points": round(self.points, 2),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Losses:
    """The points one cause costs, and the slots that lose them, the heaviest first."""

    cause: str
    slots: tuple[Lost, ...]

    @property
    def points(self) -> float:
        return sum(lost.points for lost in self.slots)

    @property
    def title(self) -> str:
        return CAUSES[self.cause][0]

    @property
    def correct(self) -> str:
        return CAUSES[self.cause][1]

    def describe(self) -> str:
        """`Gates that fail: 25 points in 3 slots; put the gate in place in CI`."""
        slots = counted(len(self.slots), "slot")
        return f"{self.title}: {in_points(self.points)} points in {slots}; {self.correct}"

    def as_dict(self) -> dict[str, object]:
        return {
            "cause": self.cause,
            "title": self.title,
            "correct": self.correct,
            "points": round(self.points, 2),
            "slots": [lost.as_dict() for lost in self.slots],
        }


def in_points(value: float) -> str:
    """Points as the report says them: whole points from ten, a tenth from one, a hundredth below, and never a
    loss rounded away to nothing."""
    if value >= 10:
        return f"{value:.0f}"
    if value >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}" if value >= 0.005 else "<0.01"


def _strength(value: float) -> str:
    """A strength, or what takes it, to three significant digits: a small cost is not rounded away."""
    return f"{value:.3g}"


def _detail(cell: Cell, cause: str, weakened: dict[str, tuple[float, float]]) -> str:
    """For a tool weakened by what is turned off: its strength, and how much its configuration and comments take."""
    if cause != "turned-off" or not cell.strengths:
        return ""
    tool, strength = max(zip(cell.tools, cell.strengths, strict=True), key=lambda pair: pair[1])
    said = f"{tool} at {_strength(strength)}"
    if tool not in weakened:
        return said
    configuration, comments = weakened[tool]
    return (
        f"{said}: {_strength(configuration)} turned off in its configuration, "
        f"{_strength(comments)} by comments in the code"
    )


def losses(scored: Score) -> tuple[Losses, ...]:
    """Where `scored` loses its points: each cause with the slots it costs, heaviest first; nothing for a full score."""
    weakened = dict(scored.weakened)
    by_cause: dict[str, list[Lost]] = {}
    for cell in scored.cells:
        for cause, slots in cell.lacks():
            if slots > 1e-9:
                points, detail = 100.0 * slots / scored.slots, _detail(cell, cause, weakened)
                lost = Lost(check=cell.check, ecosystem=cell.ecosystem, unit=cell.unit, points=points, detail=detail)
                by_cause.setdefault(cause, []).append(lost)
    found = (
        Losses(cause=cause, slots=tuple(sorted(slots, key=lambda lost: (-lost.points, lost.check, lost.where))))
        for cause, slots in by_cause.items()
    )
    return tuple(sorted(found, key=lambda each: -each.points))


__all__ = ["CAUSES", "Losses", "Lost", "in_points", "losses"]
