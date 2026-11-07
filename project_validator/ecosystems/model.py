"""The model of a language ecosystem: how it is recognised, what its CI toolchains are, and judging per ecosystem.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from project_validator.core import Context, Project, Result, Status
from project_validator.facts import Command

__all__ = [
    "C_FAMILY",
    "BuildSystem",
    "Ecosystem",
    "ToolchainPatterns",
    "check_each_ecosystem",
    "combined",
    "ecosystems_for",
    "labelled",
    "languages_of",
]

C_FAMILY = frozenset({"C", "C++"})


def toml_members(*table: str) -> Callable[[str], tuple[str, ...]]:
    """Workspace members listed under `members` in TOML `table` (Cargo's `workspace`, uv's `tool.uv.workspace`)."""

    def members(text: str) -> tuple[str, ...]:
        try:
            value: object = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return ()
        for key in (*table, "members"):
            value = value.get(key) if isinstance(value, Mapping) else None
        return tuple(str(member) for member in value) if isinstance(value, list) else ()

    return members


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildSystem:
    """A build system recognised by its build files, in any directory.

    Each of `files` is a file name (`CMakeLists.txt`), a glob pattern for one (`*.csproj`), or a glob pattern ending
    in `/` for a directory (`*.xcodeproj/`), which is recognised by the files inside it.
    The languages it builds are `languages`, plus those `declared_languages` reads from one of its build files.
    A directory for which `is_build_tree` is true holds its build output and is never inspected.
    `build_types` reads the build types (`debug`, `release`) a command of the build system builds.
    `members` reads, from a build file, the directories (globs relative to it) of the workspace it declares; each
    member is a unit of the project of its own (see `project_validator.facts.structure.Unit`).
    """

    name: str
    files: tuple[str, ...]
    languages: frozenset[str] = frozenset()
    declared_languages: Callable[[str], frozenset[str]] | None = None
    is_build_tree: Callable[[Path], bool] | None = None
    build_types: Callable[[Command], frozenset[str]] | None = None
    members: Callable[[str], tuple[str, ...]] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainPatterns:
    """How a CI job names the versions of a language toolchain, and how a job that names none shows it uses one."""

    language: str
    versions: tuple[re.Pattern[str], ...]
    usage: re.Pattern[str]


# Ecosystems are registry singletons: they compare and hash by identity.
@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Ecosystem:
    """A language ecosystem: how it is recognised. What it is judged by are components of its profile (tools,
    practices, questions' declarations), found rather than listed.

    It is recognised by its build systems' files, its `source_suffixes`, and `detect`, a probe that reads the project
    (with `Project.read_head`) and returns the ecosystem's languages it finds, for intent that file names cannot
    show. `ambiguous_suffixes` count only once the ecosystem is recognised one of those ways, because another
    ecosystem uses them too (`.pl`: Perl or Prolog) or they do not tell its languages apart (`.h`: C or C++); each
    maps to the language it adds, or to None for a file of the ecosystem that adds no language.

    A project using none of its `build_systems` is taken to use `default_build_system`.
    """

    label: str
    languages: frozenset[str]
    build_systems: tuple[BuildSystem, ...] = ()
    source_suffixes: Mapping[str, str] | None = None
    ambiguous_suffixes: Mapping[str, str | None] | None = None
    detect: Callable[[Project], frozenset[str]] | None = None
    toolchain: ToolchainPatterns | None = None
    # How a CI job shows it builds with the ecosystem, besides naming or using its toolchain.
    ci_usage: re.Pattern[str] | None = None
    default_build_system: BuildSystem | None = None

    def __repr__(self) -> str:
        return f"Ecosystem({self.label})"

    def used_by(self, text: str) -> bool:
        """Whether CI configuration `text` builds with or runs the ecosystem's toolchain."""
        patterns = (self.ci_usage, *((self.toolchain.usage, *self.toolchain.versions) if self.toolchain else ()))
        return any(pattern.search(text) for pattern in patterns if pattern is not None)

    def used_build_systems(self, build_systems: frozenset[str]) -> tuple[BuildSystem, ...]:
        """The ecosystem's build systems among `build_systems`, or its default build system when none is."""
        used = tuple(system for system in self.build_systems if system.name in build_systems)
        return used or ((self.default_build_system,) if self.default_build_system else ())


_SEVERITY = (Status.SKIP, Status.PASS, Status.WARN, Status.FAIL, Status.ERROR)


def _severity(status: Status) -> int:
    return _SEVERITY.index(status)


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems among `languages`, in the order they are supported."""
    return tuple(ecosystem for ecosystem in supported if ecosystem.languages & languages)


def combined(results: Mapping[Ecosystem, Result]) -> Result:
    """One result for several ecosystems, labelled by ecosystem where they differ; ecosystems a practice does not apply
    to are left out, unless all are."""
    if not results:
        return Result(status=Status.SKIP, message="no recognised ecosystem in the project")
    if judged := {ecosystem: result for ecosystem, result in results.items() if result.status is not Status.SKIP}:
        results = judged
    if len(set(results.values())) == 1:
        return next(iter(results.values()))  # one result, or the same for every ecosystem
    return labelled({ecosystem.label: result for ecosystem, result in results.items()})


def labelled(results: Mapping[str, Result]) -> Result:
    """One result for several subjects, each named by its label: the worst status wins."""
    return Result(
        status=max((result.status for result in results.values()), key=_severity),
        message="; ".join(f"{label}: {result.message}" for label, result in results.items()),
        details=tuple(f"{label}: {detail}" for label, result in results.items() for detail in result.details),
    )


def check_each_ecosystem[Rules](
    context: Context, rules: Mapping[Ecosystem, Rules], judge: Callable[[Rules, Context], Result]
) -> Result:
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled."""
    used = ecosystems_for(context.structure.languages, rules)
    return combined({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})
