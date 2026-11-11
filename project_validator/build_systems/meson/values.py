"""Meson values, each in the builds it is in.

A Meson value is a string, a number, a boolean, an array, a dictionary or an object (a compiler, a target). What
the build decides (the compiler, the host system, the build type, an option) is not known: a boolean is a `Truth`,
the builds it is true in; `cc.get_id()` is a `Symbol` that comparing with a name turns into one; anything else is
`Unknown`, as written. An expression takes several values when the variables it reads were set in branches:
`Choices` are those values, each with the builds it takes it in. An array's elements carry their own builds too, so
that `flags += ['-Wall']` in a branch adds one element rather than doubling the choices.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from project_validator.facts.conditions import ALWAYS, NEVER, Condition, Dimension, both, either, negated, requiring

# At most this many values of one expression are followed; the rest are left out.
MOST_CHOICES = 32


@dataclass(frozen=True, slots=True)
class Truth:
    """A boolean: the builds it is true in."""

    when: Condition


@dataclass(frozen=True, slots=True)
class Symbol:
    """A value that names a dimension's value in each build (`cc.get_id()`), written `text`."""

    dimension: Dimension
    text: str


@dataclass(frozen=True, slots=True)
class Unknown:
    """A value that is not known (an option, a program's output), as written."""

    text: str


@dataclass(frozen=True, slots=True)
class Array:
    """An array: each element in the builds it is in."""

    items: tuple[tuple[Value, Condition], ...] = ()


@dataclass(frozen=True, slots=True)
class Dictionary:
    items: tuple[tuple[str, Value], ...] = ()


@dataclass(frozen=True, slots=True)
class Compiler:
    """`meson.get_compiler('cpp')`."""

    language: str


@dataclass(frozen=True, slots=True)
class Object:
    """Another object (a target, a program, `meson`, `host_machine`), by what made it."""

    kind: str
    name: str = ""


type Value = str | int | Truth | Symbol | Unknown | Array | Dictionary | Compiler | Object
type Choices = list[tuple[Value, Condition]]

TRUE, FALSE = Truth(ALWAYS), Truth(NEVER)


def single(value: Value) -> Choices:
    return [(value, ALWAYS)]


def truth(value: Value) -> Condition:
    """The builds in which a value, taken as a boolean, is true."""
    if isinstance(value, Truth):
        return value.when
    if isinstance(value, (Unknown, Symbol)):
        return requiring(value.text)
    return ALWAYS if value not in ("", 0, Array()) else NEVER


def holds(choices: Choices) -> Condition:
    """The builds in which an expression with these values is true."""
    return either(*(both(when, truth(value)) for value, when in choices))


def combined(*choices: Choices) -> Iterator[tuple[tuple[Value, ...], Condition]]:
    """Each combination of the values of several expressions, in the builds all of them take it in."""
    found: list[tuple[tuple[Value, ...], Condition]] = [((), ALWAYS)]
    for values in choices:
        found = [
            ((*chosen, value), held) for chosen, when in found for value, other in values if (held := both(when, other))
        ][:MOST_CHOICES]
    return iter(found)


def assigned(old: Choices | None, new: Choices, when: Condition) -> Choices:
    """A variable's values once it is set to `new` in the builds `when` names; other builds keep `old`."""
    kept = [(value, held) for value, other in old or () if (held := both(other, negated(when)))]
    return [*kept, *((value, held) for value, other in new if (held := both(other, when)))][:MOST_CHOICES]


def elements(choices: Choices) -> Iterator[tuple[Value, Condition]]:
    """The elements of an expression's values, flattened (Meson flattens nested arrays in arguments), each in its
    builds."""
    for value, when in choices:
        if isinstance(value, Array):
            yield from elements([(item, both(when, held)) for item, held in value.items])
        else:
            yield value, when


def strings(choices: Choices) -> Iterator[tuple[str, Condition]]:
    return ((value, when) for value, when in elements(choices) if isinstance(value, str))


def array(values: Iterable[tuple[Value, Condition]]) -> Array:
    return Array(tuple((value, when) for value, when in values if when))


__all__ = [
    "FALSE",
    "MOST_CHOICES",
    "TRUE",
    "Array",
    "Choices",
    "Compiler",
    "Dictionary",
    "Object",
    "Symbol",
    "Truth",
    "Unknown",
    "Value",
    "array",
    "assigned",
    "combined",
    "elements",
    "holds",
    "single",
    "strings",
    "truth",
]
