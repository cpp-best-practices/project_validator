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

from project_validator.core import Context

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
class BuildTypes:
    """A compiled ecosystem, whose CI must build each of its platforms (along `axis`) in every build configuration."""

    axis: ToolchainAxis


def ignored_at_top_level(names: str) -> re.Pattern[str]:
    """Globs that ignore one of `names` at the top of the repository, as a directory or with all of its contents."""
    return re.compile(rf"(?:\*\*/|/)?(?:{names})(?:/\**)?", re.IGNORECASE)


def directories(*names: str) -> tuple[str, ...]:
    """The paths of `names` as an ignore rule sees them: the directory itself and what is inside it."""
    return tuple(path for name in names for path in (name, f"{name}/"))
