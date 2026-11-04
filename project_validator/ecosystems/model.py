"""The model of a language ecosystem: how it is recognised, what its CI toolchains are, and judging per ecosystem.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from project_validator.core import Context, Result, Status

if TYPE_CHECKING:
    from project_validator.ci import Job

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


class _Versioned(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def version(self) -> str: ...


def toolchain_versions(toolchains: Iterable[_Versioned], language: str) -> frozenset[str]:
    return frozenset(toolchain.version for toolchain in toolchains if toolchain.language == language)


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainAxis:
    """What varies between the CI jobs of an ecosystem besides the OS: compilers, or language toolchain versions."""

    noun: str
    of_job: Callable[[Job], frozenset[str]]
    runner_default: Callable[[Job], bool]

    def plural(self) -> str:
        return f"{self.noun}s"


def _never(_: Job) -> bool:
    return False


def versions_axis(noun: str, language: str) -> ToolchainAxis:
    """An axis of the `language` toolchain versions a job names; there is no runner default."""

    def of_job(job: Job) -> frozenset[str]:
        return toolchain_versions(job.toolchains, language)

    return ToolchainAxis(noun=noun, of_job=of_job, runner_default=_never)


# Ecosystems are registry singletons: they compare and hash by identity.
@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Ecosystem:
    label: str
    languages: frozenset[str]
    build_systems: tuple[BuildSystem, ...] = ()
    source_suffixes: Mapping[str, str] | None = None
    toolchain: ToolchainPatterns | None = None
    axis: ToolchainAxis | None = None

    def __repr__(self) -> str:
        return f"Ecosystem({self.label})"


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
