"""What every reader shares: where something is in a file (`Span`), and why a file does not parse (`ParseError`).

Each reader's own syntax error (CMake's, Meson's, JSON's, Cabal's, YAML's) is a `ParseError`, so a caller can catch
any of them, and a fact built from one (see `project_validator.facts.settings.unreadable`) says where it went wrong.
"""

from __future__ import annotations

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
