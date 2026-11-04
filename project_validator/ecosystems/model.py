"""The model of a language ecosystem: how it is recognised, what its CI toolchains are, and judging per ecosystem.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from project_validator.core import Context, Result, Status
from project_validator.rules import ToolchainAxis, toolchain_versions, versions_axis

__all__ = [
    "C_FAMILY",
    "BuildSystem",
    "Ecosystem",
    "ToolchainAxis",
    "ToolchainPatterns",
    "check_each_ecosystem",
    "ecosystems_for",
    "languages_of",
    "toolchain_versions",
    "versions_axis",
]

C_FAMILY = frozenset({"C", "C++"})


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildSystem:
    """A build system recognised by its build file names, in any directory.

    The languages it builds are `languages`, plus those `declared_languages` reads from one of its build files.
    A directory for which `is_build_tree` is true holds its build output and is never inspected.
    """

    name: str
    files: tuple[str, ...]
    languages: frozenset[str] = frozenset()
    declared_languages: Callable[[str], frozenset[str]] | None = None
    is_build_tree: Callable[[Path], bool] | None = None


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

    `rules` holds at most one rule of each type; a practice whose rule type an ecosystem lacks does not apply to it.
    """

    label: str
    languages: frozenset[str]
    build_systems: tuple[BuildSystem, ...] = ()
    source_suffixes: Mapping[str, str] | None = None
    toolchain: ToolchainPatterns | None = None
    rules: tuple[object, ...] = field(default=())

    def __post_init__(self) -> None:
        kinds = [type(rule) for rule in self.rules]
        if duplicates := sorted({kind.__name__ for kind in kinds if kinds.count(kind) > 1}):
            raise ValueError(f"{self.label} has several rules of type {', '.join(duplicates)}")

    def __repr__(self) -> str:
        return f"Ecosystem({self.label})"

    def rule[R](self, kind: type[R]) -> R | None:
        return next((rule for rule in self.rules if isinstance(rule, kind)), None)


_SEVERITY = (Status.PASS, Status.WARN, Status.FAIL, Status.ERROR)


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems in `languages`; a project whose languages are unknown is judged as C/C++."""
    supported = tuple(supported)
    used = tuple(ecosystem for ecosystem in supported if ecosystem.languages & (languages or C_FAMILY))
    return used or supported


def _combined(results: Mapping[Ecosystem, Result]) -> Result:
    if len(results) == 1:
        return next(iter(results.values()))
    return Result(
        status=max((result.status for result in results.values()), key=_SEVERITY.index),
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
    return _combined({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})
