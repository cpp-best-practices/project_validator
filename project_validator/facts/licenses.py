"""Licenses: the license files of the project and the licenses they hold, and the license each manifest declares.

The license files are read by a shared reader (see `project_validator.tools.licenses`); a profile reads the license
its manifests declare (`declared_license_reader`).
"""

import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from project_validator.facts import Fact, Origin
from project_validator.facts.settings import SettingsReader


@dataclass(frozen=True, slots=True, kw_only=True)
class LicenseFile(Fact):
    """A license file, and the SPDX identifiers of the licenses it holds: none when it is not recognised."""

    licenses: frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclaredLicense(Fact):
    """A manifest of `languages` (`Cargo.toml`, a `.csproj`) that declares the license as an SPDX expression."""

    expression: str
    languages: frozenset[str]


def declared_license_reader(
    *, name: str, files: tuple[str, ...], languages: frozenset[str], declared: Callable[[str], str | None]
) -> SettingsReader:
    """A reader of the manifests `files`, of `languages`, whose license `declared` reads from their text as an SPDX
    expression (None when they declare none, or do not parse: their package manager says so)."""

    def read(path: str, text: str) -> Iterator[Fact]:
        try:
            expression = declared(text)
        except ValueError:  # TOML and JSON errors are ValueErrors
            return
        if expression:
            yield DeclaredLicense(origin=Origin(path=path), expression=expression, languages=languages)

    return SettingsReader(name=name, files=files, read=read)


def toml_license(table: str) -> Callable[[str], str | None]:
    """The license declared as `license = "<SPDX expression>"` in `table` of a TOML manifest; the older table form
    (`license = {text = ...}`) names no SPDX expression."""

    def declared(text: str) -> str | None:
        found = tomllib.loads(text).get(table)
        license_ = found.get("license") if isinstance(found, dict) else None
        return license_ if isinstance(license_, str) else None

    return declared


__all__ = ["DeclaredLicense", "LicenseFile", "declared_license_reader", "toml_license"]
