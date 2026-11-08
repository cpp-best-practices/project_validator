"""The model of a language ecosystem: how it is recognised and what its CI toolchains are. Judging per ecosystem is
`project_validator.judging`'s.

Everything the validator knows about one ecosystem lives in that ecosystem's profile module next to this one.
"""

import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from project_validator.build_systems.model import C_FAMILY, BuildSystem
from project_validator.core import Project

__all__ = [
    "C_FAMILY",
    "VERSION",
    "BuildSystem",
    "Ecosystem",
    "ToolchainPatterns",
    "ecosystems_for",
    "languages_of",
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
    """How a CI job names the versions of a language toolchain, and how a job that names none shows it uses one.
    `labelled` patterns name a toolchain by something other than its version, written with their label: a Stackage
    snapshot pins a GHC (a resolver `lts-22` is "Stackage lts-22")."""

    language: str
    versions: tuple[re.Pattern[str], ...]
    usage: re.Pattern[str]
    labelled: tuple[tuple[re.Pattern[str], str], ...] = ()


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
    commands: str,
    setup: Iterable[str] = (),
    labelled: Iterable[tuple[re.Pattern[str], str]] = (),
) -> ToolchainPatterns:
    """How CI names a `language` toolchain, and shows it uses one. A version (`version`, a regular expression with one
    group) is named by a setup action's `inputs` (`go-version: 1.22`), by a container's `images` tag (`golang:1.22`;
    `image_version` where images are tagged otherwise) or by `more` patterns of the language's own; a job that names
    none uses the toolchain when it runs its `commands` (a regular expression) or a `setup` action (`setup-go`)."""
    named = (
        *(rf"\b{re.escape(name)}\W+{version}" for name in inputs),
        *(rf"\b{re.escape(image)}:{image_version or version}" for image in images),
        *more,
    )
    usage = "|".join((commands, *(rf"\bsetup-{re.escape(name)}\b" for name in setup)))
    return ToolchainPatterns(
        language=language,
        versions=tuple(re.compile(found) for found in named),
        usage=re.compile(usage),
        labelled=tuple(labelled),
    )


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
        toolchain = self.toolchain
        named = (toolchain.usage, *toolchain.versions, *(found for found, _ in toolchain.labelled)) if toolchain else ()
        patterns = (self.ci_usage, *named)
        return any(pattern.search(text) for pattern in patterns if pattern is not None)

    def used_build_systems(self, build_systems: frozenset[str]) -> tuple[BuildSystem, ...]:
        """The ecosystem's build systems among `build_systems`, or its default build system when none is."""
        used = tuple(system for system in self.build_systems if system.name in build_systems)
        return used or ((self.default_build_system,) if self.default_build_system else ())


def languages_of(ecosystems: Iterable[Ecosystem]) -> frozenset[str]:
    return frozenset().union(*(ecosystem.languages for ecosystem in ecosystems))


def ecosystems_for(languages: frozenset[str], supported: Iterable[Ecosystem]) -> tuple[Ecosystem, ...]:
    """The supported ecosystems among `languages`, in the order they are supported."""
    return tuple(ecosystem for ecosystem in supported if ecosystem.languages & languages)
