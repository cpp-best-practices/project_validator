"""The Cabal file format, shared by package descriptions (`*.cabal`) and project files (`cabal.project`): fields
(`name: value`, continued on more indented lines) and sections (`library`, `executable app`, `common warnings`,
`package *`, `if flag(dev)`), nested by indentation or by braces (`library {` … `}`, `} else {`). Comments are lines
starting with `--`.

A component's fields include those of the `common` stanzas it imports, and those under conditions (`if`, `elif`,
`else`), each with the conditions it needs. Nothing is evaluated: a condition is kept as written.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple

from project_validator.parsing import ParseError, Span

_FIELD = re.compile(r"(?P<name>[A-Za-z][\w-]*)\s*:(?P<value>.*)$")
# The sections that are components of a package, or of a project the options apply to.
COMPONENTS = frozenset({"library", "executable", "test-suite", "benchmark", "foreign-library", "package"})
COMPONENTS |= {"program-options"}


class CabalSyntaxError(ParseError):
    pass


class Field(NamedTuple):
    """A field (its name in lower case), its value (its continuation lines joined by newlines), and where it is
    written, from its name to the end of its last line."""

    name: str
    value: str
    span: Span


@dataclass(slots=True)
class Section:
    """A section: its kind (`executable`, `if`), the rest of its header (`app`, `flag(dev)`), where its header is,
    and what it holds."""

    kind: str
    name: str
    span: Span
    fields: list[Field] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


# The kinds of section, which braces may enclose (`library {`); a `{` ending any other line is text.
_SECTIONS = COMPONENTS | {"common", "flag", "source-repository", "source-repository-package", "custom-setup"}
_SECTIONS |= {"if", "elif", "else"}
# Braces nest as deep as indentation would: a line inside n pairs of braces is as indented as n of these, plus its own.
_BRACED = 10_000


def _lines(text: str) -> Iterator[tuple[Span, int, str]]:
    """(where its content is, indentation, content) of each line that is not blank or a comment; a section's braces
    are taken as indentation (see `_BRACED`), and the lines that only open or close them are left out."""
    depth = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise CabalSyntaxError(f"line {number}: tab in indentation", number)
        while stripped.startswith("}"):
            depth, stripped = max(depth - 1, 0), stripped[1:].strip()
        opens = stripped.endswith("{") and (stripped == "{" or stripped.split()[0].lower() in _SECTIONS)
        stripped = stripped.removesuffix("{").strip() if opens else stripped
        if stripped:
            column = raw.index(stripped) + 1
            indent = len(raw) - len(raw.lstrip())
            yield Span(number, column, number, column + len(stripped)), depth * _BRACED + indent, stripped
        depth += opens


def parse(text: str) -> Section:
    """The file as a section of kind "" holding its top-level fields and sections."""
    root = Section(kind="", name="", span=Span(0))
    # The open sections, with the indentation of their header; the field being read, with its indentation.
    stack: list[tuple[int, Section]] = [(-1, root)]
    current: tuple[int, Section, int] | None = None
    for span, indent, content in _lines(text):
        if current is not None and indent > current[0]:
            _, section, index = current
            name, value, start = section.fields[index]
            joined = f"{value}\n{content}" if value else content
            section.fields[index] = Field(name, joined, Span(start.line, start.column, span.end_line, span.end_column))
            continue
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if match := _FIELD.match(content):
            parent.fields.append(Field(match["name"].lower(), match["value"].strip(), span))
            current = (indent, parent, len(parent.fields) - 1)
            continue
        kind, _, name = content.partition(" ")
        section = Section(kind=kind.lower(), name=name.strip(), span=span)
        parent.sections.append(section)
        stack.append((indent, section))
        current = None
    return root


@dataclass(frozen=True, slots=True)
class Value:
    """A field's value in a component, and the conditions it needs (as written: `flag(dev)`, `not impl(ghc < 9)`)."""

    value: str
    requires: frozenset[str] = frozenset()
    span: Span | None = None


def _conditional(section: Section, requires: frozenset[str], previous: list[str]) -> frozenset[str]:
    """The conditions a branch needs: its own, and the negation of the branches before it in its chain."""
    negated = frozenset(f"not {condition}" for condition in previous)
    own = frozenset() if section.kind == "else" else frozenset({section.name})
    return requires | negated | own


def _values(
    section: Section, name: str, requires: frozenset[str], commons: dict[str, Section], seen: set[str]
) -> Iterator[Value]:
    """The values of field `name` in `section`, its conditional branches and the common stanzas it imports."""
    for found, value, span in section.fields:
        if found == name:
            yield Value(value, requires, span)
        elif found == "import":
            for imported in (part.strip() for part in value.split(",")):
                if imported in commons and imported not in seen:
                    yield from _values(commons[imported], name, requires, commons, seen | {imported})
    chain: list[str] = []
    for child in section.sections:
        if child.kind not in ("if", "elif", "else"):
            continue
        if child.kind == "if":
            chain = []
        yield from _values(child, name, _conditional(child, requires, chain), commons, seen)
        chain.append(child.name)


@dataclass(frozen=True, slots=True)
class Component:
    kind: str
    name: str
    span: Span

    def __str__(self) -> str:
        return f"{self.kind} {self.name}".strip()


def components(root: Section) -> Iterator[Component]:
    for section in root.sections:
        if section.kind in COMPONENTS:
            yield Component(section.kind, section.name, section.span)


def values(root: Section, name: str) -> Iterator[tuple[Component, Value]]:
    """Each component's values of the field `name`, with the conditions they need."""
    commons = {section.name: section for section in root.sections if section.kind == "common"}
    for section in root.sections:
        if section.kind in COMPONENTS:
            component = Component(section.kind, section.name, section.span)
            for found in _values(section, name, frozenset(), commons, set()):
                yield component, found


def top_level(root: Section, name: str) -> str | None:
    return next((value for found, value, _ in root.fields if found == name), None)


__all__ = ["CabalSyntaxError", "Component", "Field", "Section", "Value", "components", "parse", "top_level", "values"]
