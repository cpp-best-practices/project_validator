"""The syntax of CMake `if()` (and `elseif()`, `while()`) arguments: operands to a tree, by CMake's precedence.

CMake recognizes keywords after it expands the arguments, so the tree is built from the expanded operands; it never
consults a variable (`project_validator.build_systems.cmake.conditions` evaluates it). Precedence is CMake's:
parentheses, unary tests, binary tests, NOT, AND, then OR. A quoted operand is never a keyword.

Malformed arguments, which CMake would reject, parse as far as they go: a missing operand is empty, a missing `)` is
assumed, and what follows a complete condition is ignored.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

UNARY = frozenset(
    {"EXISTS", "COMMAND", "DEFINED", "TARGET", "TEST", "POLICY", "IS_DIRECTORY", "IS_SYMLINK", "IS_ABSOLUTE"}
)
BINARY = frozenset(
    {"EQUAL", "LESS", "LESS_EQUAL", "GREATER", "GREATER_EQUAL", "STREQUAL", "STRLESS", "STRLESS_EQUAL", "STRGREATER"}
    | {"STRGREATER_EQUAL", "VERSION_EQUAL", "VERSION_LESS", "VERSION_LESS_EQUAL", "VERSION_GREATER"}
    | {"VERSION_GREATER_EQUAL", "PATH_EQUAL", "MATCHES", "IN_LIST", "IS_NEWER_THAN"}
)


@dataclass(frozen=True, slots=True)
class Operand:
    text: str
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class Truth:
    """A lone operand: a constant, or the variable it names."""

    operand: Operand


@dataclass(frozen=True, slots=True)
class Test:
    """A unary test (`DEFINED X`, `EXISTS path`)."""

    operator: str
    operand: Operand


@dataclass(frozen=True, slots=True)
class Comparison:
    left: Operand
    operator: str
    right: Operand


@dataclass(frozen=True, slots=True)
class Not:
    operand: Node


@dataclass(frozen=True, slots=True)
class All:
    """`a AND b AND ...`"""

    operands: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class Any:
    """`a OR b OR ...`"""

    operands: tuple[Node, ...]


type Node = Truth | Test | Comparison | Not | All | Any


@dataclass(slots=True)
class _Parser:
    operands: Sequence[Operand]
    position: int = 0

    def _peek(self) -> Operand | None:
        return self.operands[self.position] if self.position < len(self.operands) else None

    def _keyword(self, *keywords: str) -> bool:
        operand = self._peek()
        if operand is not None and not operand.quoted and operand.text in keywords:
            self.position += 1
            return True
        return False

    def _next(self) -> Operand:
        operand = self._peek() or Operand("")
        self.position += 1
        return operand

    def _chain(self, keyword: str, operand: Callable[[], Node], node: Callable[[tuple[Node, ...]], Node]) -> Node:
        found = [operand()]
        while self._keyword(keyword):
            found.append(operand())
        return found[0] if len(found) == 1 else node(tuple(found))

    def disjunction(self) -> Node:
        return self._chain("OR", self.conjunction, Any)

    def conjunction(self) -> Node:
        return self._chain("AND", self.negation, All)

    def negation(self) -> Node:
        return Not(self.negation()) if self._keyword("NOT") else self.test()

    def test(self) -> Node:
        if self._keyword("("):
            found = self.disjunction()
            self._keyword(")")
            return found
        operand = self._peek()
        if operand is not None and not operand.quoted and operand.text in UNARY:
            self.position += 1
            return Test(operand.text, self._next())
        left = self._next()
        following = self._peek()
        if following is None or following.quoted or following.text not in BINARY:
            return Truth(left)
        self.position += 1
        return Comparison(left, following.text, self._next())


def parse(operands: Sequence[Operand]) -> Node | None:
    """The tree of `if()` arguments; None for no arguments."""
    return _Parser(operands).disjunction() if operands else None
