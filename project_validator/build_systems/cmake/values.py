"""CMake values: what a variable holds, and what an argument expands to.

A variable set under a condition holds its value only in the builds that condition names, so a value is a sequence
of `Item`s, each with the builds it is in. Expanding `${NAME}` gives each value it can take, with the builds it takes
it in; a variable the project never sets (an option, a cache variable, one the build defines) is kept as written,
`${NAME}`, for the conditions that read it to name.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import groupby

from project_validator.facts import Origin
from project_validator.facts.conditions import ALWAYS, Condition, both, either, negated

# At most this many values of one argument are followed; the rest are left out.
MOST_VALUES = 32


@dataclass(frozen=True, slots=True)
class Item:
    """An element of a variable's value, in the builds `when` names, and where it was set (None: by CMake)."""

    text: str
    when: Condition = ALWAYS
    origin: Origin | None = None


type Lookup = Callable[[str], tuple[Item, ...] | None]
"""A variable's value; None when it is not set."""


@dataclass(frozen=True, slots=True)
class Value:
    """A value an argument takes, in the builds `when` names, and where the variable it came from was set; `choice`
    counts the values the argument takes before it (0: the first, where the project sets what it references)."""

    text: str
    when: Condition = ALWAYS
    origin: Origin | None = None
    choice: int = 0
    # The quoted argument it is a value of (its index), which is one argument whatever value it takes; -1 for others.
    argument: int = -1


_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "0": "\0"}
# `\;` keeps a semicolon from separating list elements; it stands in for that semicolon until the list is split.
ESCAPED_SEMICOLON = ""
_START = re.compile(r"\$(?:ENV|CACHE)?\{|\\.", re.DOTALL)


def reference(name: str) -> str:
    """How a variable that is not set is kept: as written."""
    return f"${{{name}}}"


_REFERENCE = re.compile(r"\$\{([^${}]+)\}")


def referenced(text: str) -> str | None:
    """The variable `text` is the unexpanded reference of, if it is one."""
    match = _REFERENCE.fullmatch(text)
    return match[1] if match else None


def _closing(text: str, start: int) -> int:
    """The position of the brace closing the reference whose name starts at `start`, nested references skipped."""
    depth = 1
    for position in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[position], 0)
        if depth == 0:
            return position
    return -1


def _variable(name: str, kind: str, lookup: Lookup) -> list[Value]:
    if kind != "${":
        return [Value(f"{kind}{name}}}")]  # the environment and the cache are not known
    items = lookup(name)
    if items is None:
        return [Value(reference(name))]
    values = [
        Value(";".join(item.text for item in group), when, next(iter(group), Item("")).origin)
        for when, group in ((when, list(group)) for when, group in groupby(items, key=lambda item: item.when))
    ]
    # Where the project does not set it, configuring may (`-DNAME=value`).
    rest = negated(either(*(value.when for value in values)))
    return [*values, Value(reference(name), rest)] if rest else values


def _origin(prefix: Value, suffix: Value) -> Origin | None:
    """Where a value was set: a variable's value taken whole was set where the variable was; one joined to more text
    is set where it is joined (None: where the command is)."""
    if not suffix.text:
        return prefix.origin
    return suffix.origin if not prefix.text else None


def _combined(prefixes: list[Value], suffixes: list[Value]) -> list[Value]:
    found = [
        Value(prefix.text + suffix.text, when, _origin(prefix, suffix))
        for prefix in prefixes
        for suffix in suffixes
        if (when := both(prefix.when, suffix.when))
    ]
    return found[:MOST_VALUES]


def expanded(text: str, lookup: Lookup) -> list[Value]:
    """The values `text` takes once its references and escapes are expanded."""
    values = [Value("")]
    position = 0
    for match in _START.finditer(text):
        if match.start() < position:
            continue
        literal = text[position : match.start()]
        if match[0].startswith("\\"):
            values = _combined(values, [Value(literal + _escaped(match[0][1]))])
            position = match.end()
            continue
        end = _closing(text, match.end())
        if end < 0:
            break
        names = expanded(text[match.end() : end], lookup)
        found = [
            Value(value.text, both(name.when, value.when), value.origin or name.origin)
            for name in names
            for value in _variable(name.text, match[0], lookup)
        ]
        values = _combined(_combined(values, [Value(literal)]), found)
        position = end + 1
    return _combined(values, [Value(text[position:])])


def _escaped(character: str) -> str:
    if character == ";":
        return ESCAPED_SEMICOLON
    return _ESCAPES.get(character, character)


def elements(text: str) -> Iterator[str]:
    """The elements of a list, separated by semicolons outside generator expressions (`$<...>`); empty ones are left
    out, as CMake leaves them out of unquoted arguments."""
    depth, start = 0, 0
    for position, character in enumerate(text):
        if text.startswith("$<", position):
            depth += 1
        elif character == ">" and depth:
            depth -= 1
        elif character == ";" and not depth:
            if element := text[start:position]:
                yield element.replace(ESCAPED_SEMICOLON, ";")
            start = position + 1
    if element := text[start:]:
        yield element.replace(ESCAPED_SEMICOLON, ";")


__all__ = ["ESCAPED_SEMICOLON", "Item", "Lookup", "Value", "elements", "expanded", "reference", "referenced"]
