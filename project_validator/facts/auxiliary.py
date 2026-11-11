"""Auxiliary code: what `--auxiliary` names as not the product's, for the judging layer to hold to every practice as
advisory (its failures are warnings that say so) instead of as the product's.

Every source outside vendored directories is the product's by default, whatever directory it is in: a C++ project's
`scripts/release.py` makes Python one of its languages, judged in full. `--auxiliary` names the code that is not, by
its role (`tooling`, `docs`, `example`, `benchmark`, `test`: see `project_validator.facts.roles`), by its language or
ecosystem (`python`, `c/c++`), or by a directory it is in (`scripts/`). What is named is a fact of the project
(`AuxiliaryCode`), so the questions can tell the code it names (`selectors`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from project_validator.ecosystems import registered
from project_validator.facts import Fact, Facts
from project_validator.facts.roles import AUXILIARY, role
from project_validator.facts.tools import within


@dataclass(frozen=True, slots=True, kw_only=True)
class AuxiliaryCode(Fact):
    """What `--auxiliary` named, as given."""

    named: tuple[str, ...]


def _languages_named(name: str) -> frozenset[str]:
    """The languages a name (lower case) is: a language's, or every language of the ecosystem it labels."""
    return frozenset(
        language
        for ecosystem in registered()
        for language in ecosystem.languages
        if name in (language.lower(), ecosystem.label.lower())
    )


@dataclass(frozen=True, slots=True)
class Selectors:
    """What `--auxiliary` named, resolved: each role, language (as the ecosystems spell it) and directory (without
    its trailing slash) to the name it was given as. A name is a role or a language before it is a directory
    (`c/c++` is the ecosystem); a directory is anything else with a slash in it (`scripts/`, `tools/legacy`)."""

    roles: Mapping[str, str]
    languages: Mapping[str, str]
    directories: Mapping[str, str]

    @classmethod
    def parse(cls, named: Iterable[str]) -> Selectors:
        """Resolve what was named; a name that is no role, language, ecosystem or directory is a `ValueError`."""
        roles: dict[str, str] = {}
        languages: dict[str, str] = {}
        directories: dict[str, str] = {}
        for name in named:
            if name.lower() in AUXILIARY:
                roles.setdefault(name.lower(), name)
            elif found := _languages_named(name.lower()):
                for language in found:
                    languages.setdefault(language, name)
            elif "/" in name and name.strip("/"):
                directories.setdefault(name.strip("/"), name)
            else:
                roles_ = ", ".join(sorted(AUXILIARY))
                raise ValueError(
                    f"--auxiliary {name}: not a role ({roles_}), a language or ecosystem, or a directory (with a /)"
                )
        return cls(roles, languages, directories)

    def matching(self, path: str, language: str | None, *, directory: bool = False) -> str:
        """What names the code at `path` (a file, or a `directory`) in `language`, as it was given: its role, its
        language, or a directory it is at or below; "" when nothing does (the code is the product's)."""
        if found := self.roles.get(role(path, directory=directory)):
            return found
        if language is not None and (found := self.languages.get(language)):
            return found
        return next((name for parent, name in self.directories.items() if within(path, parent)), "")


def selectors(facts: Facts) -> Selectors:
    """What `--auxiliary` named for the project the facts are about, resolved once."""

    def resolve() -> Selectors:
        named = facts.of(AuxiliaryCode)
        return Selectors.parse(named[0].named if named else ())

    return facts.shared("auxiliary", resolve)


__all__ = ["AuxiliaryCode", "Selectors", "selectors"]
