"""The rule types practices are judged by; each ecosystem profile supplies its own rule of the types that apply to it.

A practice (a check) is generic over its rule type and never names an ecosystem; see
`project_validator.ecosystems.practice`. A practice that only one ecosystem can have, such as `cxx-extensions`, is
written the same way: only that ecosystem's profile supplies the rule. Rules that depend on the build system are
supplied by the profile's build systems instead (see `project_validator.ecosystems.model.Ecosystem.rule_for`).
"""

import re
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
    """How an ecosystem reports branch coverage, and the path (or MC/DC) coverage that is a bonus on top of it.

    An ecosystem whose tools cannot measure branches names the finest `granularity` they can measure instead, e.g.
    statement coverage for Go; `branch` then holds the patterns that report it.
    """

    searched: str
    texts: Evidence
    branch: tuple[Pattern, ...]
    granularity: str = "branch"
    path: tuple[Pattern, ...] = ()
    path_hint: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TestSuite:
    """How an ecosystem's tests are found, and how CI is recognised running them."""

    found: Callable[[Context], Result]
    runs: tuple[Pattern, ...]
    runner: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WarningPolicy:
    """The warning settings an ecosystem must enable, every setting it recognises, and where they are found.

    Settings are listed joined by `separator`: flags as on a command line, named tools as a list.
    """

    kind: str
    recognised: tuple[Pattern, ...]
    required: Callable[[Context], tuple[Pattern, ...]]
    texts: Evidence
    separator: str = " "


@dataclass(frozen=True, slots=True, kw_only=True)
class WarningsAsErrors:
    """The settings that make warnings fail the build, where they are `searched`, and how to enable them."""

    flags: tuple[Pattern, ...]
    texts: Evidence
    searched: str
    hint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Hardening:
    """The security hardening options an ecosystem must enable, all of them, and where they are found.

    An ecosystem whose options depend on more than presence, e.g. on the compilers in CI, supplies its own `judge`.
    """

    texts: Evidence
    options: tuple[Pattern, ...] = ()
    judge: Callable[[Context], Result] | None = None


DEFAULT_LENGTH_LIMIT = 30
SUGGESTED_LIZARD = f"lizard --length {DEFAULT_LENGTH_LIMIT}"


@dataclass(frozen=True, slots=True, kw_only=True)
class FunctionLimits:
    """Function length can be limited in this ecosystem; lizard measures every one of them.

    `without_lizard` judges the ecosystem's own way of limiting function length when lizard is not run.
    """

    without_lizard: Callable[[Context], Result] | None = None


def ignored_at_top_level(names: str) -> re.Pattern[str]:
    """Globs that ignore one of `names` at the top of the repository, as a directory or with all of its contents."""
    return re.compile(rf"(?:\*\*/|/)?(?:{names})(?:/\**)?", re.IGNORECASE)


def directories(*names: str) -> tuple[str, ...]:
    """The paths of `names` as an ignore rule sees them: the directory itself and what is inside it."""
    return tuple(path for name in names for path in (name, f"{name}/"))


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildOutputs:
    """The build outputs of an ecosystem that must never be committed, and the ignore entries that ignore them.

    A glob entry ignores the outputs when it is one of `globs`; a regular expression when it matches one of `paths`.
    """

    name: str
    globs: re.Pattern[str]
    paths: tuple[str, ...]
    hint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CompilerExtensions:
    """Judges whether the language is compiled as standardised, without compiler extensions (C/C++ only)."""

    judge: Callable[[Context], Result]
