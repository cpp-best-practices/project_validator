"""The rule types practices are judged by; each ecosystem profile supplies its own rule of the types that apply to it.

A practice (a check) is generic over its rule type and never names an ecosystem; see
`project_validator.ecosystems.practice`. A practice that only one ecosystem can have, such as `cxx-extensions`, is
written the same way: only that ecosystem's profile supplies the rule. Rules that depend on the build system are
supplied by the profile's build systems instead (see `project_validator.ecosystems.model.Ecosystem.rule_for`).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

from project_validator.core import Context, Result
from project_validator.evidence import toml_value
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
class BuildTypes:
    """A compiled ecosystem, whose CI must build each of its platforms (along `axis`) in every build configuration."""

    axis: ToolchainAxis


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
    """The binary hardening an ecosystem must enable, all of it, and where it is found.

    Binary hardening is what the build inserts into the binary to make it harder to exploit: stack protectors,
    control-flow protection, checked library calls, position-independent executables, release-mode overflow checks.
    It is not code security scanning (see `project_validator.facts.security`) nor dependency auditing (see
    `project_validator.facts.audit`); an ecosystem that builds no binary has no hardening rule.

    An ecosystem whose options depend on more than presence, e.g. on the compilers in CI, supplies its own `judge`.
    """

    texts: Evidence
    options: tuple[Pattern, ...] = ()
    judge: Callable[[Context], Result] | None = None


def _always(_: Context) -> bool:
    return True


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyManagement:
    """How an ecosystem's dependencies are declared, and where they are locked.

    `managed` says how the project's dependencies are managed ("declared in pyproject.toml", "managed with Cargo"),
    or None when it declares none; `hint` then suggests how to manage any it has. `locked` names where they are
    locked, or None when they are not; an ecosystem without lockfiles has no `locked`. A lock is asked for only when
    `lock_required`, e.g. for a binary crate. `vendor_outputs` are files that show a vendored directory is the
    package manager's own output (`vendor/modules.txt`), not hand-copied code.
    """

    managed: Callable[[Context], str | None]
    hint: str = ""
    locked: Callable[[Context], str | None] | None = None
    lock_required: Callable[[Context], bool] = _always
    lock_hint: str = ""
    vendor_outputs: tuple[str, ...] = ()


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
    `artifacts` recognise committed outputs (see `artifact`).
    """

    name: str
    globs: re.Pattern[str]
    paths: tuple[str, ...]
    hint: str
    artifacts: tuple[str, ...] = ()

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
        return path if any(fnmatchcase(parts[-1], glob) for glob in files) else None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompilerExtensions:
    """Judges whether the language is compiled as standardised, without compiler extensions (C/C++ only)."""

    judge: Callable[[Context], Result]


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclaredLicense:
    """Where an ecosystem's manifest declares the project's license: `declared` reads it as an SPDX expression."""

    manifest: str
    declared: Callable[[Context], str | None]


def toml_license(manifest: str, table: str) -> DeclaredLicense:
    """The license declared as `license = "<SPDX expression>"` in `table` of the TOML file `manifest`; the older
    table form (`license = {text = ...}`) names no SPDX expression."""

    def declared(context: Context) -> str | None:
        license_ = toml_value(context, manifest, table, "license")
        return license_ if isinstance(license_, str) else None

    return DeclaredLicense(manifest=manifest, declared=declared)
