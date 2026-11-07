"""What every build system is: the files it is recognised by, the languages it builds, its build trees, the build
types its commands build and the workspace members it declares. A build system is defined once (with Make, CMake and
Meson here; the others in the profile of the only language they build) and named by the ecosystems that use it."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project_validator.facts import Command

C_FAMILY = frozenset({"C", "C++"})


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildSystem:
    """A build system recognised by its build files, in any directory.

    Each of `files` is a file name (`CMakeLists.txt`), a glob pattern for one (`*.csproj`), or a glob pattern ending
    in `/` for a directory (`*.xcodeproj/`), which is recognised by the files inside it.
    The languages it builds are `languages`, plus those `declared_languages` reads from one of its build files, given
    the file's path and text.
    A directory for which `is_build_tree` is true holds its build output and is never inspected.
    `build_types` reads the build types (`debug`, `release`) a command of the build system builds.
    `members` reads, from a build file, the directories (globs relative to it) of the workspace it declares; each
    member is a unit of the project of its own (see `project_validator.facts.structure.Unit`).
    """

    name: str
    files: tuple[str, ...]
    languages: frozenset[str] = frozenset()
    declared_languages: Callable[[str, str], frozenset[str]] | None = None
    is_build_tree: Callable[[Path], bool] | None = None
    build_types: Callable[[Command], frozenset[str]] | None = None
    members: Callable[[str], tuple[str, ...]] | None = None


__all__ = ["C_FAMILY", "BuildSystem"]
