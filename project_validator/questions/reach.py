"""How much of a language's code the runs of a gate's tools reach (upstream #333): a run reaches the paths its command
names, or all of its scope when it names none. Only the product's code counts: a run that skips tests, tooling or
examples misses none of it, nor one that skips a build file written in a language (Package.swift, project.clj) or a
tool's configuration (vitest.config.ts), nor what an outside generator wrote (protoc's, SWIG's).
Weighed by lines."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.ecosystems import formats
from project_validator.facts import Facts
from project_validator.facts.analysis import ANALYSIS, TYPE_CHECK
from project_validator.facts.formatting import FORMAT
from project_validator.facts.structure import BuildFile, SourceFile, Unit
from project_validator.facts.tools import ToolRun, owner

# The aspects a run provides for the files it is given: formatting and analysing them.
PATHED = frozenset({FORMAT, ANALYSIS, TYPE_CHECK})


@dataclass(frozen=True, slots=True, kw_only=True)
class Reach:
    """The share of a unit's product lines of a language its runs reach, and the folders (or files) they miss, each
    with its lines."""

    share: float
    lines: int
    missed: tuple[tuple[str, int], ...]


# Tools' own configuration written in the language (vitest.config.ts, eslint.config.js, .prettierrc.cjs): not the
# product's code a linter is pointed at.
_CONFIGURATION = ("*.config.*", ".*")


def _configuration(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatchcase(name, pattern) for pattern in _CONFIGURATION)


def _place(path: str, unit: str) -> str:
    """Where a missed file is, for findings: the folder it is in below its unit, or the file itself."""
    relative = PurePosixPath(path).relative_to(unit) if unit != "." else PurePosixPath(path)
    top = relative.parts[0]
    return (
        str(PurePosixPath(unit) / top) + ("/" if len(relative.parts) > 1 else "")
        if unit != "."
        else top + ("/" if len(relative.parts) > 1 else "")
    )


def _product_files(language: str, unit: str, facts: Facts) -> list[SourceFile]:
    """The unit's product files of `language`, but for build files written in a language and tools' configuration."""
    units = tuple(found.directory for found in facts.of(Unit)) or (".",)
    # A format's own files may be build files (CMakeLists.txt, BUILD.bazel): they are its code.
    builds = {found.origin.path for found in facts.of(BuildFile)} if language not in formats() else set()
    return [
        source
        for source in facts.of(SourceFile)
        if source.language == language
        and source.role == "product"
        and source.path not in builds
        and not _configuration(source.path)
        and not source.generator  # an outside generator's output is not the project's to check
        and owner(str(PurePosixPath(source.path).parent), units) == unit
    ]


def reach(language: str, unit: str, facts: Facts, runs: Iterable[ToolRun]) -> Reach | None:
    """What `runs` reach of `language`'s product code in `unit`; None when they reach all of it (or it has no lines)."""
    runs = tuple(runs)
    files = _product_files(language, unit, facts)
    total = sum(source.lines for source in files)
    missed: dict[str, int] = {}
    for source in files:
        if not any(run.reaches(source.path) for run in runs):
            place = _place(source.path, unit)
            missed[place] = missed.get(place, 0) + source.lines
    lost = sum(missed.values())
    if not lost:
        return None
    return Reach(share=(total - lost) / total, lines=total, missed=tuple(sorted(missed.items())))


__all__ = ["PATHED", "Reach", "reach"]
