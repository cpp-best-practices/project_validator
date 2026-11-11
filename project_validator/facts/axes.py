"""What varies between a language's CI jobs besides the OS: its compilers (C and C++), or the versions of its
toolchain (Python 3.13 and 3.14). A `ToolchainAxis`, a component of the profile, reads it from each `Job` fact. A
compiled language's axis is `compiled`: its CI must build each platform in every build configuration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from project_validator.components import known
from project_validator.facts.jobs import Job


class _Versioned(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def version(self) -> str: ...


def toolchain_versions(toolchains: Iterable[_Versioned], language: str) -> frozenset[str]:
    return frozenset(toolchain.version for toolchain in toolchains if toolchain.language == language)


def _never(_job: Job) -> bool:
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainAxis:
    """What varies between the CI jobs of `languages` besides the OS (named `noun`): `of_job` reads it from a job,
    and `runner_default` says whether a job uses its runner's default. `compiled`: the languages have build types."""

    languages: frozenset[str]
    noun: str
    of_job: Callable[[Job], frozenset[str]]
    runner_default: Callable[[Job], bool] = _never
    compiled: bool = False

    def plural(self) -> str:
        return f"{self.noun}s"


def versions_axis(noun: str, toolchain: str, languages: frozenset[str], *, compiled: bool = False) -> ToolchainAxis:
    """An axis of the versions of the `toolchain` (Python, JDK) a job names; there is no runner default."""

    def of_job(job: Job) -> frozenset[str]:
        return toolchain_versions(job.toolchains, toolchain)

    return ToolchainAxis(languages=languages, noun=noun, of_job=of_job, compiled=compiled)


def known_axes() -> tuple[ToolchainAxis, ...]:
    """Every axis defined by a module of the shared build systems, the shared tools or a profile."""
    return known(ToolchainAxis)


def axis_of(language: str) -> ToolchainAxis | None:
    return next((axis for axis in known_axes() if language in axis.languages), None)


def handled(*, compiled: bool = False) -> Callable[[], frozenset[str]]:
    """The languages some axis covers (with `compiled`, only those with build types)."""
    return lambda: frozenset().union(*(axis.languages for axis in known_axes() if axis.compiled or not compiled))


__all__ = ["ToolchainAxis", "axis_of", "handled", "known_axes", "toolchain_versions", "versions_axis"]
