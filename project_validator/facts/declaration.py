"""Whether each schema declares what it is. A schema that names its dialect (a JSON Schema's `$schema`, a
description's `openapi` version, a `.proto` file's `syntax`) is read as its author meant, and one that names itself
(an `$id`, a `targetNamespace`, a `package`) can be referred to. A format's profile defines a `Declares` for the
schemas of the format: which files they are, and what each declares. Every such schema of the project's formats is a
`SchemaDeclaration` fact, read once at extraction. Nothing here judges: the `schema-declared` question counts, and
its policy decides."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

from project_validator.components import known
from project_validator.core import Project
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.roles import role


@dataclass(frozen=True, slots=True, kw_only=True)
class Declaration:
    """What one schema declares: `declared`, each declaration by name (`$schema` -> the dialect's URL); `missing`,
    the names of what it does not declare; `outdated`, why what it declares is superseded (a dialect older than
    2019-09), when it is."""

    declared: Mapping[str, str]
    missing: tuple[str, ...] = ()
    outdated: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Declares:
    """How the schemas of one format declare themselves: `find(project)` yields the paths of the format's schemas,
    `read(text)` what one declares (None when the text is not a schema that can be read: `data-wellformed` says so).
    `what` names the declarations asked for (`dialect ($schema) and $id`), for the policy's messages. A profile
    defines one per format; they are found, not listed."""

    format: str
    what: str
    find: Callable[[Project], Iterable[str]]
    read: Callable[[str], Declaration | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaDeclaration(Fact):
    """A schema of `format` and what it declares (see `Declaration`). `role` is the file's (see
    `project_validator.facts.roles`): a test suite's schemas may be undeclared on purpose."""

    format: str
    what: str
    role: str = "product"
    declared: Mapping[str, str]
    missing: tuple[str, ...] = ()
    outdated: str | None = None

    @property
    def path(self) -> str:
        return self.origin.path


def known_declarers() -> tuple[Declares, ...]:
    """Every `Declares` a profile or a plugin defines."""
    return known(Declares)


def declared_formats() -> frozenset[str]:
    """The formats whose schemas declare themselves (plugins add some, so it is asked when needed)."""
    return frozenset(declares.format for declares in known_declarers())


def declaration_facts(project: Project, facts: Facts, declarers: Iterable[Declares]) -> Iterator[SchemaDeclaration]:
    """Each schema of the project's formats (vendored ones apart), with what it declares."""
    from project_validator.facts.structure import project_formats  # structure reads the profiles, which declare

    formats = project_formats(facts)
    for declares in declarers:
        if declares.format not in formats:
            continue
        for path in declares.find(project):
            if (found := role(path)) == "vendored" or (read := declares.read(project.read_text(path))) is None:
                continue
            yield SchemaDeclaration(
                origin=Origin(path=path),
                format=declares.format,
                what=declares.what,
                role=found,
                declared=read.declared,
                missing=read.missing,
                outdated=read.outdated,
            )


def declaring(names: Mapping[str, object], *, outdated: str | None = None) -> Declaration:
    """A declaration of `names` (what is asked for -> its value, None or empty when not declared), as strings."""
    declared = {name: str(value) for name, value in names.items() if value not in (None, "")}
    return Declaration(
        declared=declared, missing=tuple(name for name in names if name not in declared), outdated=outdated
    )


__all__ = [
    "Declaration",
    "Declares",
    "SchemaDeclaration",
    "declaration_facts",
    "declared_formats",
    "declaring",
    "known_declarers",
]
