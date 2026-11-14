"""The support matrix: what each check recognises for each ecosystem, generated from the registry.

It is printed by `--support-matrix`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from project_validator.core import Check
from project_validator.ecosystems import applies_to, registered
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.tools import tools_for

type Cell = tuple[str, ...] | None  # tool names (maybe none) where the check applies; None where it does not

LEGEND = """\
What project_validator checks for each ecosystem, and the tools it recognises for it, generated from the registry
by `python -m project_validator --support-matrix`. A cell lists the tools the check recognises; `✓` means the check
applies without naming tools; `—` means it does not apply. A tool several ecosystems share (CodeQL, osv-scanner,
lizard) is listed once below the table with the ecosystems it reads, and `↓` stands for it in a cell it alone fills.
"""

# A tool in the cells of this many ecosystems is shared: listed once below the table.
SHARED_FROM = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class Row:
    check: str
    description: str
    cells: tuple[Cell, ...]  # one per ecosystem of the matrix


type Shared = tuple[tuple[str, tuple[str, ...]], ...]  # (tool, the ecosystems whose cells of a row name it)


@dataclass(frozen=True, slots=True, kw_only=True)
class SupportMatrix:
    ecosystems: tuple[str, ...]  # labels, registration order
    rows: tuple[Row, ...]  # checks with languages, in the order given
    everywhere: tuple[str, ...]  # checks of every project, in the order given

    def shared(self, row: Row) -> Shared:
        """The tools of `row` that several ecosystems (`SHARED_FROM` or more) share, each with those ecosystems."""
        counted: dict[str, list[str]] = {}
        for label, cell in zip(self.ecosystems, row.cells, strict=True):
            for tool in cell or ():
                counted.setdefault(tool, []).append(label)
        return tuple((tool, tuple(labels)) for tool, labels in counted.items() if len(labels) >= SHARED_FROM)


def _cell(check: Check, ecosystem: Ecosystem) -> Cell:
    if ecosystem.label not in applies_to(check):
        return None
    names = (
        tool.name for tool in (tools_for(check.aspect) if check.aspect else ()) if tool.languages & ecosystem.languages
    )
    return tuple(dict.fromkeys(names))


def support_matrix(checks: Sequence[Check]) -> SupportMatrix:
    """The support matrix of `checks` over the ecosystems now registered."""
    ecosystems = registered()
    rows = tuple(
        Row(check=check.name, description=check.description, cells=tuple(_cell(check, e) for e in ecosystems))
        for check in checks
        if check.languages
    )
    return SupportMatrix(
        ecosystems=tuple(e.label for e in ecosystems),
        rows=rows,
        everywhere=tuple(check.name for check in checks if not check.languages),
    )


def _render_cell(cell: Cell, shared: frozenset[str] = frozenset()) -> str:
    """A cell without its shared tools: `↓` when they were all it named."""
    if cell is None:
        return "—"
    own = [name.replace("|", "\\|") for name in cell if name not in shared]
    if own:
        return ", ".join(own)
    return "↓" if cell else "✓"


def _render_row(matrix: SupportMatrix, row: Row) -> str:
    shared = frozenset(tool for tool, _ in matrix.shared(row))
    return f"| `{row.check}` | " + " | ".join(_render_cell(cell, shared) for cell in row.cells) + " |"


def _render_shared(matrix: SupportMatrix) -> str:
    """The shared tools of each row, each with the ecosystems whose cells it fills."""
    lines = []
    for row in matrix.rows:
        if shared := matrix.shared(row):
            tools = "; ".join(f"{tool} ({', '.join(labels)})" for tool, labels in shared)
            lines.append(f"- `{row.check}`: {tools}")
    if not lines:
        return ""
    return "\nTools of several ecosystems, once for all the cells they fill:\n\n" + "\n".join(lines) + "\n"


def render(matrix: SupportMatrix) -> str:
    """The matrix as a Markdown page."""
    lines = [
        "| Check | " + " | ".join(matrix.ecosystems) + " |",
        "|---|" + "---|" * len(matrix.ecosystems),
        *(_render_row(matrix, row) for row in matrix.rows),
    ]
    page = "# Support matrix\n\n" + LEGEND + "\n" + "\n".join(lines) + "\n" + _render_shared(matrix)
    if not matrix.everywhere:
        return page
    everywhere = ", ".join(f"`{name}`" for name in matrix.everywhere)
    return page + f"\nChecks of every project, whatever its languages: {everywhere}.\n"


def as_dict(matrix: SupportMatrix) -> dict[str, object]:
    """The matrix as JSON-ready data."""
    return {
        "ecosystems": list(matrix.ecosystems),
        "rows": [
            {
                "check": row.check,
                "description": row.description,
                "cells": {
                    label: None if cell is None else list(cell)
                    for label, cell in zip(matrix.ecosystems, row.cells, strict=True)
                },
            }
            for row in matrix.rows
        ],
        "everywhere": list(matrix.everywhere),
        "shared": {
            row.check: {tool: list(labels) for tool, labels in shared}
            for row in matrix.rows
            if (shared := matrix.shared(row))
        },
    }
