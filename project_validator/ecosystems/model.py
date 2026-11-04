"""The model of a language ecosystem: how it is recognised, what its CI toolchains are, and judging per ecosystem.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from project_validator.core import Context, Project, Result, Status
from project_validator.rules import ToolchainAxis, toolchain_versions, versions_axis

__all__ = [
    "C_FAMILY",
    "BuildSystem",
    "Ecosystem",
    "ToolchainAxis",
    "ToolchainPatterns",
    "check_each_ecosystem",
    "combined",
    "ecosystems_for",
    "languages_of",
    "toolchain_versions",
    "versions_axis",
]

C_FAMILY = frozenset({"C", "C++"})


def _reject_duplicate_rules(owner: str, rules: tuple[object, ...]) -> None:
    kinds = [type(rule) for rule in rules]
    if duplicates := sorted({kind.__name__ for kind in kinds if kinds.count(kind) > 1}):
        raise ValueError(f"{owner} has several rules of type {', '.join(duplicates)}")


def _rule_of[R](rules: tuple[object, ...], kind: type[R]) -> R | None:
    return next((rule for rule in rules if isinstance(rule, kind)), None)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildSystem:
    """A build system recognised by its build files, in any directory.

    Each of `files` is a file name (`CMakeLists.txt`), a glob pattern for one (`*.csproj`), or a glob pattern ending
    in `/` for a directory (`*.xcodeproj/`), which is recognised by the files inside it.
    The languages it builds are `languages`, plus those `declared_languages` reads from one of its build files.
    A directory for which `is_build_tree` is true holds its build output and is never inspected.
    `rules` are those of its ecosystem's practices that depend on the build system (see `Ecosystem.rule_for`).
    """

    name: str
    files: tuple[str, ...]
    languages: frozenset[str] = frozenset()
    declared_languages: Callable[[str], frozenset[str]] | None = None
    is_build_tree: Callable[[Path], bool] | None = None
    rules: tuple[object, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        _reject_duplicate_rules(self.name, self.rules)

    def rule[R](self, kind: type[R]) -> R | None:
        return _rule_of(self.rules, kind)


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainPatterns:
    """How a CI job names the versions of a language toolchain, and how a job that names none shows it uses one."""

    language: str
    versions: tuple[re.Pattern[str], ...]
    usage: re.Pattern[str]


# Ecosystems are registry singletons: they compare and hash by identity.
@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Ecosystem:
    """A language ecosystem: how it is recognised, and the rules (see `project_validator.rules`) it is judged by.

    It is recognised by its build systems' files, its `source_suffixes`, and `detect`, a probe that reads the project
    (with `Project.read_head`) and returns the ecosystem's languages it finds, for intent that file names cannot
    show. `ambiguous_suffixes` count only once the ecosystem is recognised one of those ways, because another
    ecosystem uses them too (`.pl`: Perl or Prolog) or they do not tell its languages apart (`.h`: C or C++); each
    maps to the language it adds, or to None for a file of the ecosystem that adds no language.

    `rules` holds at most one rule of each type; a practice whose rule type an ecosystem lacks does not apply to it.
    Rules that depend on the build system belong to the ecosystem's `build_systems` instead; a project using none of
    them is judged as if it used `default_build_system`.
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
    rules: tuple[object, ...] = field(default=())

    def __post_init__(self) -> None:
        _reject_duplicate_rules(self.label, self.rules)

    def __repr__(self) -> str:
        return f"Ecosystem({self.label})"

    def used_by(self, text: str) -> bool:
        """Whether CI configuration `text` builds with or runs the ecosystem's toolchain."""
        patterns = (self.ci_usage, *((self.toolchain.usage, *self.toolchain.versions) if self.toolchain else ()))
        return any(pattern.search(text) for pattern in patterns if pattern is not None)

    def rule[R](self, kind: type[R]) -> R | None:
        """The ecosystem's own rule of type `kind`, whatever the build system."""
        return _rule_of(self.rules, kind)

    def has_rule(self, kind: type[object]) -> bool:
        """Whether the ecosystem, or one of its build systems, has a rule of type `kind`."""
        return self.rule(kind) is not None or any(system.rule(kind) is not None for system in self.build_systems)

    def used_build_systems(self, build_systems: frozenset[str]) -> tuple[BuildSystem, ...]:
        """The ecosystem's build systems among `build_systems`, or its default build system when none is."""
        used = tuple(system for system in self.build_systems if system.name in build_systems)
        return used or ((self.default_build_system,) if self.default_build_system else ())

    def rule_for[R](self, kind: type[R], build_systems: frozenset[str]) -> R | None:
        """The rule of type `kind` for a project using `build_systems`: a used build system's rule comes first."""
        found = (system.rule(kind) for system in self.used_build_systems(build_systems))
        return next((rule for rule in found if rule is not None), self.rule(kind))


_SEVERITY = (Status.SKIP, Status.PASS, Status.WARN, Status.FAIL, Status.ERROR)


def _severity(status: Status) -> int:
    return _SEVERITY.index(status)


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems among `languages`, in the order they are supported."""
    return tuple(ecosystem for ecosystem in supported if ecosystem.languages & languages)


def combined(results: Mapping[Ecosystem, Result]) -> Result:
    """One result for several ecosystems; ecosystems a practice does not apply to are left out, unless all are."""
    if not results:
        return Result(status=Status.SKIP, message="no recognised ecosystem in the project")
    if judged := {ecosystem: result for ecosystem, result in results.items() if result.status is not Status.SKIP}:
        results = judged
    if len(results) == 1:
        return next(iter(results.values()))
    return Result(
        status=max((result.status for result in results.values()), key=_severity),
        message="; ".join(f"{ecosystem.label}: {result.message}" for ecosystem, result in results.items()),
        details=tuple(
            f"{ecosystem.label}: {detail}" for ecosystem, result in results.items() for detail in result.details
        ),
    )


def check_each_ecosystem[Rules](
    context: Context, rules: Mapping[Ecosystem, Rules], judge: Callable[[Rules, Context], Result]
) -> Result:
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled."""
    used = ecosystems_for(context.structure.languages, rules)
    return combined({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})
