"""The wording messages and views share, so that a count or a folder reads the same everywhere."""

from __future__ import annotations


def counted(count: int, noun: str, plural: str | None = None) -> str:
    """`1 file`, `3 files`: a count and its noun, singular only for one."""
    return f"{count} {noun if count == 1 else plural or f'{noun}s'}"


def folder(directory: str, *, slash: bool = True) -> str:
    """How a folder of the project ("." for the root) is named: `the root`, else `src/app/` (`src/app` for a unit,
    which messages name without the slash)."""
    if directory == ".":
        return "the root"
    return f"{directory}/" if slash else directory


__all__ = ["counted", "folder"]
