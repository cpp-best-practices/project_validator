"""Build outputs: what building the project writes into it (`target/`, `__pycache__/`, object files), which version
control must ignore and never track.

A `BuildOutput` is a component of the profile (or build system) whose builds write it. The ignore files' entries are
read by settings readers (see `project_validator.tools.version_control`) as `IgnoreEntry` facts; the tracked files
that are build outputs are found once, when the repository is read (see `project_validator.facts.repository`), as
`CommittedOutput` facts.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.components import known
from project_validator.facts import Fact


class Syntax(enum.StrEnum):
    GLOB = "glob"
    REGEX = "regex"


@dataclass(frozen=True, slots=True, kw_only=True)
class IgnoreEntry(Fact):
    """An entry of an ignore file (its origin): `written` as it appears there, and the `pattern` it ignores in its
    `syntax`. A rooted glob `pattern` starts with "/", as in a .gitignore."""

    written: str
    pattern: str
    syntax: Syntax


@dataclass(frozen=True, slots=True, kw_only=True)
class CommittedOutput(Fact):
    """A tracked file, or the outermost tracked directory (its path ends in "/"), that is a build output, as the
    build output of `languages` called `output` names it."""

    output: str
    languages: frozenset[str]


def _regex_matches_any(pattern: str, paths: Iterable[str]) -> bool:
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    return any(compiled.search(path) for path in paths)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildOutput:
    """The build output called `name` that the builds of `languages` write (with `build_systems`, those of one of
    them only: an hpack package is built by Stack or Cabal), which must never be committed.

    A glob ignore entry ignores it when `globs` matches it whole; a regular expression when it matches one of
    `paths`. `artifacts` recognise it among the tracked files (see `artifact`), except files named one of
    `not_artifacts` (Go's `go.mod` is not a compiled Fortran module). `hint` says how to ignore it.
    """

    name: str
    languages: frozenset[str]
    globs: re.Pattern[str]
    paths: tuple[str, ...]
    hint: str
    artifacts: tuple[str, ...] = ()
    not_artifacts: tuple[str, ...] = ()
    build_systems: frozenset[str] = frozenset()

    def ignored_by(self, entry: IgnoreEntry) -> bool:
        if entry.syntax is Syntax.REGEX:
            return _regex_matches_any(entry.pattern, self.paths)
        return self.globs.fullmatch(entry.pattern) is not None

    def artifact(self, path: str) -> str | None:
        """The build output `path` is, or is inside, as one of `artifacts` names it; None when it is not one.

        A glob without a slash names a file anywhere; one ending in a slash, a directory anywhere, and one that also
        starts with a slash, a directory at the top of the project. A file in an output directory is the outermost
        such directory.
        """
        parts = PurePosixPath(path).parts
        directories = [glob for glob in self.artifacts if glob.endswith("/")]
        for depth, part in enumerate(parts[:-1]):
            if any(fnmatchcase(part, glob.strip("/")) for glob in directories if depth == 0 or glob[0] != "/"):
                return "/".join(parts[: depth + 1]) + "/"
        files = (glob for glob in self.artifacts if not glob.endswith("/"))
        if parts[-1] in self.not_artifacts:
            return None
        return path if any(fnmatchcase(parts[-1], glob) for glob in files) else None


def ignored_at_top_level(names: str) -> re.Pattern[str]:
    """Globs that ignore one of `names` at the top of the repository, as a directory or with all of its contents."""
    return re.compile(rf"(?:\*\*/|/)?(?:{names})(?:/\**)?", re.IGNORECASE)


def directories(*names: str) -> tuple[str, ...]:
    """The paths of `names` as an ignore rule sees them: the directory itself and what is inside it."""
    return tuple(path for name in names for path in (name, f"{name}/"))


def directory_output(
    directory: str,
    *,
    languages: frozenset[str],
    build_systems: frozenset[str] = frozenset(),
    also: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
) -> BuildOutput:
    """The commonest build output: a build system's `directory` at the top of the repository (`target`, `build`,
    `.scala-build`), ignored as that directory, with `also` the other paths worth ignoring named in the hint, and
    `artifacts` recognised among the tracked files besides the directory itself."""
    return BuildOutput(
        name=f"the {directory} directory",
        languages=languages,
        build_systems=build_systems,
        globs=ignored_at_top_level(re.escape(directory)),
        paths=directories(directory),
        hint=f"consider ignoring {' and '.join((f'{directory}/', *also))}",
        artifacts=(f"{directory}/", *artifacts),
    )


def known_build_outputs() -> tuple[BuildOutput, ...]:
    """Every build output defined by a module of the shared build systems, the shared tools or a profile."""
    return known(BuildOutput)


def outputs_of(language: str, build_systems: frozenset[str], outputs: Iterable[BuildOutput]) -> tuple[BuildOutput, ...]:
    """The build outputs of `language` for a project built with `build_systems`: those of the build systems it uses,
    and the language's own (tied to no build system), which every build of the language writes. The two add up: an
    output tied to a build system hides none."""
    found = [output for output in outputs if language in output.languages]
    return tuple(output for output in found if not output.build_systems or output.build_systems & build_systems)


__all__ = [
    "BuildOutput",
    "CommittedOutput",
    "IgnoreEntry",
    "Syntax",
    "directories",
    "directory_output",
    "ignored_at_top_level",
    "known_build_outputs",
    "outputs_of",
]
