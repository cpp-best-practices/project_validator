"""The versions of its language a project declares (upstream #412): those it supports (`requires-python = ">=3.10"`,
`rust-version`, the `go` directive, `engines.node`, the C++ standard its build sets) and those it pins its own work to
(`.python-version`, `rust-toolchain.toml`, `.nvmrc`). Shown beside the versions CI tests; never judged.

A profile reads the files that declare them (`declared_version_reader`); a language whose build already records them
reads them from its facts (`VersionsDeclared`: the C family's standards, from the build settings).
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from project_validator.components import known
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.settings import SettingsReader


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclaredVersion(Fact):
    """A version of `language` the project declares, as written: one it supports (a range, or the oldest), or, when
    `pinned`, the one its own work runs with."""

    language: str
    version: str
    pinned: bool = False


# What a reader finds in a file: the versions, as written, and whether each is pinned.
type Declares = Callable[[str], Iterable[tuple[str, bool]]]


def declared_version_reader(*, name: str, files: tuple[str, ...], language: str, declares: Declares) -> SettingsReader:
    """A reader of the files `files`, whose versions of `language` `declares` reads from their text; a file that does
    not parse declares nothing (its own tool says so)."""

    def read(path: str, text: str) -> Iterator[Fact]:
        try:
            found = list(declares(text))
        except ValueError:  # TOML and JSON errors are ValueErrors
            return
        for version, pinned in found:
            if version := version.strip():
                yield DeclaredVersion(origin=Origin(path=path), language=language, version=version, pinned=pinned)

    return SettingsReader(name=name, files=files, read=read)


def pinned_file(text: str) -> Iterator[tuple[str, bool]]:
    """A file that holds only the pinned version (`.python-version`, `.nvmrc`): its first line that is not a comment."""
    lines = (line.strip() for line in text.splitlines())
    if first := next((line for line in lines if line and not line.startswith("#")), None):
        yield first, True


def toml_version(*paths: tuple[str, ...], pinned: bool = False) -> Declares:
    """The version a TOML file holds at the first of `paths` (`("project", "requires-python")`) that holds a string."""

    def declares(text: str) -> Iterator[tuple[str, bool]]:
        document = tomllib.loads(text)
        for path in paths:
            found: object = document
            for key in path:
                found = found.get(key) if isinstance(found, dict) else None
            if isinstance(found, str):
                yield found, pinned
                return

    return declares


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionsDeclared:
    """Reads the versions a project declares from facts already recorded (the C++ standard a build sets)."""

    name: str
    read: Callable[[Facts], Iterable[DeclaredVersion]]


def declared_versions(facts: Facts) -> tuple[DeclaredVersion, ...]:
    """Every version the project declares: read from its files, and from the facts of its builds."""
    from_facts = (version for reader in known(VersionsDeclared) for version in reader.read(facts))
    return tuple(dict.fromkeys((*facts.of(DeclaredVersion), *from_facts)))


__all__ = [
    "DeclaredVersion",
    "Declares",
    "VersionsDeclared",
    "declared_version_reader",
    "declared_versions",
    "pinned_file",
    "toml_version",
]
