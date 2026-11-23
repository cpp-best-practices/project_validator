"""Templates: text with references to values (`$CC`, `$(CFLAGS)`, `{posargs}`, `${{ matrix.os }}`), substituted by one
rule.

Each language writes its references its own way, as a `Syntax`: a pattern whose `name` group (or groups starting
`name`, one per way of writing it) names the value and whose optional `default` group holds what the reference falls
back to (tox's `{posargs:tests}`). The syntax parses text to a `Template`, literal parts and `Reference`s, and
substitutes it with a lookup: a reference whose value the lookup does not know stays as written, for the reader to
decide what an unknown value means where it is (a command whose program is unknown, an argument left as written).
`SHELL` is the shell's own (`$NAME`, `${NAME}`), which GitLab CI and GitHub's `env` share; the others live with their
readers.

CMake's references, which nest (`${a_${b}}`) and whose values may each hold in only some builds, are read by its own
`build_systems.cmake.values`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Reference:
    """A reference: the name it refers to, the text it was written as, and the default it names, if any."""

    name: str
    written: str
    default: str | None = None


type Part = str | Reference
type Lookup = Callable[[Reference], str | None]


@dataclass(frozen=True, slots=True)
class Template:
    parts: tuple[Part, ...]

    @property
    def references(self) -> tuple[Reference, ...]:
        return tuple(part for part in self.parts if isinstance(part, Reference))

    @property
    def whole(self) -> Reference | None:
        """The reference that is the whole of the text, if one is."""
        return self.leading if len(self.parts) == 1 else None

    @property
    def leading(self) -> Reference | None:
        """The reference the text starts with, if it does (a command whose program is a variable)."""
        return self.parts[0] if self.parts and isinstance(self.parts[0], Reference) else None

    def substituted(self, lookup: Lookup) -> str:
        """The text with each reference replaced by its value; one whose value is not known stays as written."""
        return "".join(part if isinstance(part, str) else _value(part, lookup) for part in self.parts)


def _value(reference: Reference, lookup: Lookup) -> str:
    value = lookup(reference)
    return reference.written if value is None else value


@dataclass(frozen=True, slots=True)
class Syntax:
    """How a language writes a reference (see the module's documentation)."""

    pattern: re.Pattern[str]

    def parse(self, text: str) -> Template:
        parts: list[Part] = []
        at = 0
        for match in self.pattern.finditer(text):
            if match.start() > at:
                parts.append(text[at : match.start()])
            parts.append(self._reference(match))
            at = match.end()
        if at < len(text):
            parts.append(text[at:])
        return Template(tuple(parts))

    def _reference(self, match: re.Match[str]) -> Reference:
        groups = match.groupdict()
        name = next(value for key, value in groups.items() if key.startswith("name") and value is not None)
        return Reference(name, match[0], groups.get("default"))

    def substituted(self, text: str, lookup: Lookup, *, rounds: int = 1) -> str:
        """`text` with its references replaced by their values, again in each value, `rounds` times at most: the
        values of a language that substitutes in values too (make's `A = $(B)`) refer on."""
        for _ in range(rounds):
            expanded = self.parse(text).substituted(lookup)
            if expanded == text:
                break
            text = expanded
        return text


def known(values: Mapping[str, str]) -> Lookup:
    """A lookup of the values `values` holds, by name."""
    return lambda reference: values.get(reference.name)


# The shell's references: `$NAME` and `${NAME}`.
SHELL = Syntax(re.compile(r"\$(?:\{(?P<name>\w+)\}|(?P<name_bare>\w+))"))


__all__ = ["SHELL", "Lookup", "Reference", "Syntax", "Template", "known"]
