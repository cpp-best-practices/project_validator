"""The rule types practices are judged by; each ecosystem profile supplies its own rule of the types that apply to it.

A practice (a check) is generic over its rule type and never names an ecosystem; see
`project_validator.ecosystems.practice`. A practice that only one ecosystem can have, such as `cxx-extensions`, may
stay a plain check limited to that ecosystem's languages.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from project_validator.core import Context, Result
from project_validator.text import Pattern

if TYPE_CHECKING:
    from project_validator.ci import Job

# The texts in which an ecosystem's evidence for a practice is searched.
type Evidence = Callable[[Context], tuple[str, ...]]


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


@dataclass(frozen=True, slots=True, kw_only=True)
class Formatter:
    """Where an ecosystem's formatting style is defined, and the CI commands that enforce it.

    A formatter with a `default_style` defines the formatting even without a configuration file.
    """

    name: str
    config_file: Callable[[Context], str | None]
    runs: tuple[Pattern, ...]
    hint: str
    default_style: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildTypes:
    """A compiled ecosystem, whose CI must build each of its platforms (along `axis`) in every build configuration."""

    axis: ToolchainAxis


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageTools:
    """How an ecosystem reports branch coverage, and the path (or MC/DC) coverage that is a bonus on top of it."""

    searched: str
    texts: Evidence
    branch: tuple[Pattern, ...]
    path: tuple[Pattern, ...] = ()
    path_hint: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TestSuite:
    """How an ecosystem's tests are found, and how CI is recognised running them."""

    found: Callable[[Context], Result]
    runs: tuple[Pattern, ...]
    runner: str
