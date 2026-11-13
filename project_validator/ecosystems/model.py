"""The model of a language ecosystem: how it is recognised and what its CI toolchains are. Judging per ecosystem is
`project_validator.judging`'s.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from project_validator.build_systems.model import C_FAMILY, BuildSystem
from project_validator.core import Project
from project_validator.facts.arguments import starts_with

__all__ = [
    "C_FAMILY",
    "VERSION",
    "BuildSystem",
    "Ecosystem",
    "Kind",
    "ToolchainPatterns",
    "ecosystems_for",
    "languages_of",
    "runs",
    "subcommands",
    "toolchain_patterns",
]


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
class ToolchainPatterns:
    """How a CI job names the versions of a language toolchain, and how a job that names none shows it uses one: it
    runs one of the toolchain's `programs` (each a program and the subcommands after it, matched against each command
    the job runs: `raco cover` is Racket's, `cover` alone Perl's), or a program from one of its `directories`
    (`vendor/bin/`), or its text matches `usage` (a setup action). `labelled` patterns name a toolchain by something
    other than its version, written with their label: a Stackage snapshot pins a GHC (a resolver `lts-22` is
    "Stackage lts-22")."""

    language: str
    versions: tuple[re.Pattern[str], ...]
    programs: tuple[tuple[str, ...], ...] = ()
    directories: tuple[str, ...] = ()
    usage: re.Pattern[str] | None = None
    labelled: tuple[tuple[re.Pattern[str], str], ...] = ()

    def used_by(self, texts: Iterable[str], commands: Iterable[tuple[str, ...]]) -> bool:
        """Whether a job with `texts` that runs `commands` (each its words) uses the toolchain, without naming it."""
        return runs(commands, self.programs, self.directories) or (
            self.usage is not None and any(self.usage.search(text) for text in texts)
        )


def runs(
    commands: Iterable[tuple[str, ...]], programs: Iterable[tuple[str, ...]], directories: Iterable[str] = ()
) -> bool:
    """Whether one of `commands` (each its words) runs one of `programs` (a program by name, with the subcommands
    after it: `("go", "test")`), or a program from one of `directories`."""
    programs, directories = tuple(programs), tuple(directories)
    return any(starts_with(argv, *programs) or _from(argv, directories) for argv in commands)


def subcommands(program: str, *verbs: str) -> tuple[tuple[str, str], ...]:
    """`program` run with each of `verbs` (`subcommands("go", "build", "test")`: `go build`, `go test`)."""
    return tuple((program, verb) for verb in verbs)


def _from(argv: tuple[str, ...], directories: tuple[str, ...]) -> bool:
    path = "/" + argv[0].replace("\\", "/") if argv else ""
    return any(f"/{directory.strip('/')}/" in path for directory in directories)


VERSION = r"(\d+\.\d+(?:\.\d+)?)"
"""A version as most toolchains are named: `1.22`, `3.13.1`."""


def toolchain_patterns(
    language: str,
    *,
    version: str = VERSION,
    inputs: Iterable[str] = (),
    images: Iterable[str] = (),
    image_version: str | None = None,
    more: Iterable[str | re.Pattern[str]] = (),
    programs: Iterable[str | tuple[str, ...]] = (),
    directories: Iterable[str] = (),
    actions: Iterable[str] = (),
    setup: Iterable[str] = (),
    labelled: Iterable[tuple[re.Pattern[str], str]] = (),
) -> ToolchainPatterns:
    """How CI names a `language` toolchain and shows it uses one. A version (`version`, a regular expression with one
    group) is named by a setup action's `inputs` (`go-version: 1.22`), a container's `images` tag (`golang:1.22`;
    `image_version` where tagged otherwise) or `more` patterns. A job that names none uses the toolchain when it runs
    one of its `programs` (`"cargo"`, `("go", "test")`) or one from its `directories`, or uses `setup` or `actions`."""
    named = (
        *(rf"\b{re.escape(name)}\W+{version}" for name in inputs),
        *(rf"\b{re.escape(image)}:{image_version or version}" for image in images),
    )
    return ToolchainPatterns(
        language=language,
        versions=tuple(re.compile(found) for found in (*named, *more)),
        programs=tuple((found,) if isinstance(found, str) else found for found in programs),
        directories=tuple(directories),
        usage=_usage(setup, actions),
        labelled=tuple(labelled),
    )


def _usage(setup: Iterable[str], actions: Iterable[str]) -> re.Pattern[str] | None:
    """What in a job's text, besides a command, shows a toolchain is used: a `setup-<name>` action, an action of the
    ecosystem's (after its owner: `leafo/gh-actions-lua`); None when the toolchain has neither."""
    used = (
        *(rf"\bsetup-{re.escape(name)}\b" for name in setup),
        *(rf"(?<![\w-]){re.escape(action)}" for action in actions),
    )
    return re.compile("|".join(used)) if used else None


type Kind = Literal["language", "format"]


# Ecosystems are registry singletons: they compare and hash by identity.
@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Ecosystem:
    """An ecosystem: how it is recognised. What it is judged by are components of its profile (tools, practices,
    questions' declarations), found rather than listed.

    Its `kind` is `language` (its files are programs: it has toolchains, tests, coverage) or `format` (its files
    are data, not programs: JSON, YAML, a Dockerfile; what is asked of them is hygiene: they parse, validate, are
    formatted and linted). `languages` holds the names of its languages, or of its formats: the one key every tool,
    question and policy uses. A format has no toolchain.

    It is recognised by its build systems' files, its `source_suffixes`, its `source_names` (the names, or name
    patterns, of sources with no telling suffix: `Dockerfile`, `Dockerfile.*`), and `detect`, a probe that reads the
    project (with `Project.read_head`) and returns the ecosystem's languages it finds, for intent that file names
    cannot show. `ambiguous_suffixes` count only once the ecosystem is recognised one of those ways, because another
    ecosystem uses them too (`.pl`: Perl or Prolog) or they do not tell its languages apart (`.h`: C or C++); each
    maps to the language it adds, or to None for a file of the ecosystem that adds no language.

    A project using none of its `build_systems` is taken to use `default_build_system`.
    """

    label: str
    languages: frozenset[str]
    kind: Kind = "language"
    build_systems: tuple[BuildSystem, ...] = ()
    source_suffixes: Mapping[str, str] | None = None
    source_names: Mapping[str, str] | None = None
    ambiguous_suffixes: Mapping[str, str | None] | None = None
    detect: Callable[[Project], frozenset[str]] | None = None
    toolchain: ToolchainPatterns | None = None
    # How a CI job shows it builds with the ecosystem, besides naming or using its toolchain: the programs it runs
    # (`cmake`, `("dbt", "build")`), and a pattern for what else its text shows (a source suffix, a compiler it names).
    ci_programs: tuple[tuple[str, ...], ...] = ()
    ci_usage: re.Pattern[str] | None = None
    default_build_system: BuildSystem | None = None

    def __post_init__(self) -> None:
        if self.kind == "format" and self.toolchain is not None:
            raise ValueError(f"{self.label}: a format has no toolchain")

    def __repr__(self) -> str:
        return f"Ecosystem({self.label})"

    def used_by(self, texts: Iterable[str], commands: Iterable[tuple[str, ...]]) -> bool:
        """Whether a CI job with `texts` (its matrix values, its evidence) that runs `commands` (each its words)
        builds with the ecosystem or runs its toolchain."""
        texts, commands = tuple(texts), tuple(commands)
        if runs(commands, self.ci_programs) or (self.ci_usage and any(map(self.ci_usage.search, texts))):
            return True
        toolchain = self.toolchain
        if toolchain is None:
            return False
        named = (*toolchain.versions, *(found for found, _ in toolchain.labelled))
        return toolchain.used_by(texts, commands) or any(pattern.search(text) for pattern in named for text in texts)

    def used_build_systems(self, build_systems: frozenset[str]) -> tuple[BuildSystem, ...]:
        """The ecosystem's build systems among `build_systems`, or its default build system when none is."""
        used = tuple(system for system in self.build_systems if system.name in build_systems)
        return used or ((self.default_build_system,) if self.default_build_system else ())


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems among `languages`, in the order they are supported."""
    return tuple(ecosystem for ecosystem in supported if ecosystem.languages & languages)
