"""What every reader shares: where something is in a file (`Span`), why a file does not parse (`ParseError`) or could
not be evaluated in full (`Problem`), and how a line written over several physical lines is put back together
(`continued`).

Each reader's own syntax error (CMake's, Meson's, JSON's, Cabal's, YAML's) is a `ParseError`, so a caller can catch
any of them, and a fact built from one (see `project_validator.facts.settings.unreadable`) says where it went wrong.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    """A place in a file: where it starts (`line`, and `column` when known, both counted from 1) and, when known,
    where it ends."""

    line: int
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    def __str__(self) -> str:
        """`3:7`, or `3` without a column."""
        return f"{self.line}" if self.column is None else f"{self.line}:{self.column}"


class ParseError(ValueError):
    """Why a file does not parse (`message`), and where (`span`) when the parser says."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.span = None if line is None else Span(line, column)

    @property
    def line(self) -> int | None:
        return None if self.span is None else self.span.line

    @property
    def column(self) -> int | None:
        return None if self.span is None else self.span.column


@dataclass(frozen=True, slots=True)
class Problem:
    """Why a file could not be read or evaluated (in full), and where in it, when that is known."""

    reason: str
    span: Span | None = None


def _never(_line: str) -> bool:
    return False


def continued(
    lines: Sequence[str], index: int, *, escape: str = "\\", skipped: Callable[[str], bool] = _never
) -> tuple[list[str], int]:
    """The physical lines of the logical line starting at `lines[index]`, each without the `escape` that continues it
    on the next, and the index after them. Lines `skipped` between continuations (a Dockerfile's comments and blank
    lines) are left out; how the pieces are joined is the reader's (Make keeps a recipe's indentation, a Dockerfile
    strips each line)."""
    pieces, line = [], lines[index]
    index += 1
    while line.endswith(escape):
        pieces.append(line[: -len(escape)])
        while index < len(lines) and skipped(lines[index]):
            index += 1
        if index == len(lines):
            return pieces, index
        line = lines[index]
        index += 1
    return [*pieces, line], index
