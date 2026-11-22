"""The syntax of GitHub Actions expressions (`${{ ... }}`): text to a tree whose nodes say where they are.

Parsing never consults what a checkout shows; `project_validator.ci.github_expressions` evaluates the tree. Precedence
is GitHub's: `!`, then `<` `<=` `>` `>=`, then `==` `!=`, then `&&`, then `||`. A chain of one `&&` or `||` operator is
one node, as GitHub's runner builds it, and the tree is held to the runner's depth (`GITHUB_EXPRESSION_NESTING`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from project_validator.limits import GITHUB_EXPRESSION_NESTING
from project_validator.parsing import ParseError, Span

type Value = str | float | bool | None


class ExpressionSyntaxError(ParseError):
    """An expression that does not parse; the position is in the text as written (with its `${{`, if any)."""


@dataclass(frozen=True, slots=True)
class Literal:
    value: Value
    span: Span


@dataclass(frozen=True, slots=True)
class Reference:
    """A context property by its dotted name (`matrix.config.os`, `github.event.*`)."""

    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class Index:
    """`target[key]`, or `target[...].name` (a name after an index is a key)."""

    target: Node
    key: Node
    span: Span


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    arguments: tuple[Node, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Not:
    operand: Node
    span: Span


@dataclass(frozen=True, slots=True)
class Comparison:
    operator: str  # == != < <= > >=
    left: Node
    right: Node
    span: Span


@dataclass(frozen=True, slots=True)
class Logical:
    operator: str  # && or ||
    operands: tuple[Node, ...]
    span: Span


type Node = Literal | Reference | Index | Call | Not | Comparison | Logical
type _Operand = Callable[[], Node]

_TOKEN = re.compile(
    r"(?P<string>'(?:[^']|'')*')|(?P<number>-?\d+(?:\.\d+)?)|(?P<operator>==|!=|<=|>=|&&|\|\||[!()<>,\[\]])"
    r"|(?P<name>[A-Za-z_][\w.*-]*)|(?P<member>\.[A-Za-z_*][\w*-]*)"
)
_LITERALS: dict[str, Value] = {"true": True, "false": False, "null": None}


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    start: int
    end: int


class _Source:
    """Offsets in the text as written, as lines and columns."""

    def __init__(self, text: str) -> None:
        self.text = text

    def position(self, offset: int) -> tuple[int, int]:
        line = self.text.count("\n", 0, offset) + 1
        return line, offset - (self.text.rfind("\n", 0, offset) + 1) + 1

    def span(self, start: int, end: int) -> Span:
        return Span(*self.position(start), *self.position(end))

    def error(self, message: str, offset: int | None = None) -> ExpressionSyntaxError:
        return (
            ExpressionSyntaxError(message) if offset is None else ExpressionSyntaxError(message, *self.position(offset))
        )


def _tokens(source: _Source, start: int, end: int) -> list[_Token]:
    tokens: list[_Token] = []
    position = start
    while True:
        while position < end and source.text[position].isspace():
            position += 1
        if position == end:
            return tokens
        match = _TOKEN.match(source.text, position, end)
        if match is None or match.lastgroup is None:
            raise source.error(f"unexpected {source.text[position]!r}", position)
        tokens.append(_Token(match.lastgroup, match[0], position, match.end()))
        position = match.end()


def _start(node: Node) -> tuple[int, int | None]:
    return node.span.line, node.span.column


class _Parser:
    def __init__(self, source: _Source, tokens: list[_Token]) -> None:
        self.source, self.tokens, self.position, self.nesting = source, tokens, 0, 0

    def peek(self) -> _Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def at(self, *texts: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "operator" and token.text in texts

    def take(self, expected: str = "an operand") -> _Token:
        token = self.peek()
        if token is None:
            raise self.source.error(f"the expression ends where it expects {expected}")
        self.position += 1
        return token

    def expect(self, text: str) -> _Token:
        token = self.take(repr(text))
        if token.kind != "operator" or token.text != text:
            raise self.source.error(f"expected {text!r}, found {token.text!r}", token.start)
        return token

    def joined(self, first: Node, last: Node) -> Span:
        return Span(first.span.line, first.span.column, last.span.end_line, last.span.end_column)

    def deeper(self) -> None:
        self.nesting += 1
        if not GITHUB_EXPRESSION_NESTING.allows(self.nesting):
            raise self.source.error(f"the expression's {GITHUB_EXPRESSION_NESTING.reason}")

    def expression(self) -> Node:
        self.deeper()
        node = self.logical("||", lambda: self.logical("&&", self.equality))
        self.nesting -= 1
        return node

    def logical(self, operator: str, operand: _Operand) -> Node:
        operands = [operand()]
        while self.at(operator):
            self.take()
            operands.append(operand())
        if len(operands) == 1:
            return operands[0]
        return Logical(operator, tuple(operands), self.joined(operands[0], operands[-1]))

    def equality(self) -> Node:
        return self.comparisons(("==", "!="), self.ordering)

    def ordering(self) -> Node:
        return self.comparisons(("<", "<=", ">", ">="), self.unary)

    def comparisons(self, operators: tuple[str, ...], operand: _Operand) -> Node:
        node = operand()
        while self.at(*operators):
            operator = self.take().text
            right = operand()
            node = Comparison(operator, node, right, self.joined(node, right))
        return node

    def unary(self) -> Node:
        if not self.at("!"):
            return self.postfix(self.primary())
        bang = self.take()
        self.deeper()
        operand = self.unary()
        self.nesting -= 1
        return Not(operand, Span(*self.source.position(bang.start), operand.span.end_line, operand.span.end_column))

    def primary(self) -> Node:
        token = self.take()
        span = self.source.span(token.start, token.end)
        if token.kind == "string":
            return Literal(token.text[1:-1].replace("''", "'"), span)
        if token.kind == "number":
            return Literal(float(token.text), span)
        if token.kind == "name":
            if token.text in _LITERALS:
                return Literal(_LITERALS[token.text], span)
            return self.call(token) if self.at("(") else Reference(token.text, span)
        if token.kind == "operator" and token.text == "(":
            node = self.expression()
            self.expect(")")
            return node
        raise self.source.error(f"unexpected {token.text!r}", token.start)

    def call(self, name: _Token) -> Node:
        self.take()
        arguments: list[Node] = []
        if not self.at(")"):
            arguments.append(self.expression())
            while self.at(","):
                self.take()
                arguments.append(self.expression())
        close = self.expect(")")
        return Call(name.text, tuple(arguments), self.source.span(name.start, close.end))

    def postfix(self, node: Node) -> Node:
        while True:
            if self.at("["):
                self.take()
                key = self.expression()
                close = self.expect("]")
                end = self.source.position(close.end)
            elif (token := self.peek()) is not None and token.kind == "member":
                self.take()
                key = Literal(token.text[1:], self.source.span(token.start + 1, token.end))
                end = self.source.position(token.end)
            else:
                return node
            node = Index(node, key, Span(*_start(node), *end))


def _children(node: Node) -> tuple[Node, ...]:
    if isinstance(node, Not):
        return (node.operand,)
    if isinstance(node, Comparison):
        return (node.left, node.right)
    if isinstance(node, Logical):
        return node.operands
    if isinstance(node, Call):
        return node.arguments
    if isinstance(node, Index):
        return (node.target, node.key)
    return ()


def _check_depth(source: _Source, tree: Node) -> None:
    """Hold the tree to the runner's depth, counted without recursion (a chain of `==` nests as deep as it is long)."""
    pending = [(tree, 1)]
    while pending:
        node, depth = pending.pop()
        if not GITHUB_EXPRESSION_NESTING.allows(depth):
            raise source.error(f"the expression's {GITHUB_EXPRESSION_NESTING.reason}")
        pending.extend((child, depth + 1) for child in _children(node))


def parse(expression: str) -> Node:
    """The tree of an expression, with or without its `${{ }}`; raises ExpressionSyntaxError when it does not parse."""
    source = _Source(expression)
    start, end = 0, len(expression)
    stripped = expression.strip()
    if stripped.startswith("${{") and stripped.endswith("}}"):
        start = expression.index("${{") + 3
        end = expression.rindex("}}")
    parser = _Parser(source, _tokens(source, start, end))
    tree = parser.expression()
    if (extra := parser.peek()) is not None:
        raise source.error(f"unexpected {extra.text!r} after the expression", extra.start)
    _check_depth(source, tree)
    return tree
