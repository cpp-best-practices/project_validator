"""Auxiliary code: what `--auxiliary` names as not the product's, for the judging layer to hold to every practice as
advisory (its failures are warnings that say so) instead of as the product's.

Every source outside vendored directories is the product's by default, whatever directory it is in, but for a
language written only in auxiliary code (see `implied`): a C++ project's `scripts/release.py` is tooling, and Python
not a language of its product, while a Python project's `scripts/release.py` is the product's. `--auxiliary` names
the code that is not the product's, by its role (`tooling`, `docs`, `example`, `benchmark`, `test`: see
`project_validator.facts.roles`), by its language or ecosystem (`python`, `c/c++`), or by a directory it is in
(`scripts/`). What is named is a fact of the project (`AuxiliaryCode`), so the questions can tell the code it names
(`selectors`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from project_validator.ecosystems import registered
from project_validator.facts import Fact, Facts
from project_validator.facts.roles import AUXILIARY, fixture_data, loose_example, role
from project_validator.facts.tools import within


@dataclass(frozen=True, slots=True, kw_only=True)
class AuxiliaryCode(Fact):
    """What `--auxiliary` named, as given, and the languages written only in auxiliary code (see `implied`)."""

    named: tuple[str, ...]
    implied: tuple[str, ...] = ()


def implied(role_: str) -> str:
    """What names the code of a language written only in auxiliary code (`only in test code`), in the place of an
    option given: the language is auxiliary in code of that role, though `--auxiliary` did not name it."""
    return f"only in {role_} code"


def as_given(name: str) -> str:
    """How a name of auxiliary code reads in a finding: as the option given (`--auxiliary tooling`), or as it is
    when the code is auxiliary by its language (`only in tooling code`)."""
    return name if name.startswith("only in ") else f"--auxiliary {name}"


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
    (`c++` is the language); a directory is anything else with a slash in it (`scripts/`, `tools/legacy`). The
    languages written only in auxiliary code are `implied`: their code is named by its role (see `implied`)."""

    roles: Mapping[str, str]
    languages: Mapping[str, str]
    directories: Mapping[str, str]
    implied: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, named: Iterable[str], implied_: Iterable[str] = ()) -> Selectors:
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
        return cls(roles, languages, directories, frozenset(implied_))

    def matching(self, path: str, language: str | None, *, directory: bool = False) -> str:
        """What names the code at `path` (a file, or a `directory`) in `language`, as it was given: its role, its
        language, or a directory it is at or below, else its role when its language is written only in auxiliary
        code; "" when nothing does (the code is the product's)."""
        purpose = role(path, directory=directory)
        if found := self.roles.get(purpose):
            return found
        if language is not None and (found := self.languages.get(language)):
            return found
        if found := next((name for parent, name in self.directories.items() if within(path, parent)), ""):
            return found
        return implied(purpose) if language in self.implied and purpose in AUXILIARY else ""

    def apart(self, path: str, unit: str | None = None) -> str:
        """What sets a file (a manifest, a tool's configuration, a test) apart from the code around it: what names it
        (see `matching`), else being a test suite's data (`tests/fixtures/`), or, for configuration in `unit`, an
        example's in a unit that is not the example (`examples/perlcriticrc`: see `loose_example`; upstream #188);
        "" when it is the code's around it. An example's tests are not set apart: Awesome-CV's are its examples."""
        if found := self.matching(path, None):
            return found
        if fixture_data(path):
            return implied("test")
        return implied("example") if unit is not None and loose_example(path, unit) else ""


def selectors(facts: Facts) -> Selectors:
    """What `--auxiliary` named for the project the facts are about, resolved once."""

    def resolve() -> Selectors:
        named = facts.of(AuxiliaryCode)
        return Selectors.parse(named[0].named, named[0].implied) if named else Selectors.parse(())

    return facts.shared("auxiliary", resolve)


__all__ = ["AuxiliaryCode", "Selectors", "as_given", "implied", "selectors"]
