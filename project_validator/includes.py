"""Following one file into another: an include, an `extends`, a reusable workflow, a subdirectory.

Every reader that follows files asks the same three questions before reading the next one, answered here in one
place so that each reader says the same thing for the same reason: has this file been reached already on the way here
(a cycle), is the chain as deep as the reader's limit allows (`project_validator.limits`), and does the project hold
the file at all. The `Chain` that reached a file is its provenance: which file pulled in which, outermost first.

A refusal says why (`Refused.reason`), for the reader to report as unknown rather than cut off silently.

CMake keeps its own stack (`build_systems.cmake.evaluation`): its limit counts function calls with files, and a file
that includes itself is passed over, not reported, since its guard (`include_guard()`, or `if(DEFINED …) return()`)
may be one the evaluation cannot decide. Meson reads each `meson.build` once, from the directory tree, which cannot
cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from project_validator.limits import Limit


@dataclass(frozen=True, slots=True)
class Chain:
    """The files followed to reach the last one, outermost first."""

    paths: tuple[str, ...]

    @classmethod
    def start(cls, path: str) -> Chain:
        return cls((path,))

    @property
    def depth(self) -> int:
        """How many files were followed from the first: none for a chain that only started."""
        return len(self.paths) - 1

    def __str__(self) -> str:
        return " → ".join(self.paths)


@dataclass(frozen=True, slots=True)
class Refused:
    """Why a file is not followed; `missing` when the project does not hold it, which a reader may expect (a generated
    file it includes) where a cycle or a chain too deep is always worth reporting."""

    reason: str
    missing: bool = False


def _held(_path: str) -> bool:
    return True


def follow(
    chain: Chain, path: str, limit: Limit, exists: Callable[[str], bool] = _held, *, verb: str = "includes"
) -> Chain | Refused:
    """The chain that reaches `path` from `chain`, or why it is not followed: `path` is already on the way (a cycle,
    said with the reader's `verb`: a workflow `calls` itself, an action `uses` itself), following it would pass
    `limit`, or the project does not hold it (`exists`; left out by a reader
    whose loader says what it cannot read)."""
    if path in chain.paths:
        return Refused(f"{path} {verb} itself, through {chain}")
    if not limit.allows(chain.depth + 1):
        return Refused(limit.reason)
    if not exists(path):
        return Refused(f"{path} is not in the project", missing=True)
    return Chain((*chain.paths, path))


__all__ = ["Chain", "Refused", "follow"]
