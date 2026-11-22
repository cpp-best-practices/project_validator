"""The attributes a Nix module sets, read structurally: each attribute path (`git-hooks.hooks.rustfmt.enable`), through
nested and dotted attribute sets and past a `let … in` or a function's arguments, with its value when that is one
word (`true`, `1`, `"x"`). A value that is computed (`lib.mkIf cond { … }`, a list) is no attribute set: what it sets
is not read.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

_TOKEN = re.compile(
    r"""
    (?P<space>\s+|\#[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|\$\{[^}]*\}|[^"\\])*"|''(?:'''|''\$|''\\.|[^'])*?'')
    | (?P<word>[A-Za-z_][\w'-]*|[^\s{}\[\]();=.:"]+)
    | (?P<mark>[{}\[\]();=.:])
    """,
    re.VERBOSE | re.DOTALL,
)
_OPENING = {"{": "}", "[": "]", "(": ")"}
type Tokens = Sequence[str]


def _tokens(text: str) -> list[str]:
    return [match[0] for match in _TOKEN.finditer(text) if match.lastgroup != "space"]


def _closing(tokens: Tokens, start: int) -> int:
    """The index of the bracket closing the one at `start`, or the end when it is not closed."""
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index] in _OPENING:
            depth += 1
        elif tokens[index] in _OPENING.values():
            depth -= 1
            if depth == 0:
                return index
    return len(tokens)


def _until(tokens: Tokens, start: int, ends: frozenset[str]) -> int:
    """The index of the first of `ends` from `start` outside brackets and `let … in`, or the end."""
    index = start
    while index < len(tokens) and tokens[index] not in ends:
        if tokens[index] in _OPENING:
            index = _closing(tokens, index) + 1
        elif tokens[index] == "let":
            index = _until(tokens, index + 1, frozenset({"in"})) + 1
        else:
            index += 1
    return index


def _body(tokens: Tokens) -> Tokens:
    """An expression without the `let … in` and the function arguments (`{ pkgs, ... }:`, `pkgs:`) before it."""
    while tokens:
        if tokens[0] == "let":
            tokens = tokens[_until(tokens, 1, frozenset({"in"})) + 1 :]
        elif tokens[0] == "{" and (end := _closing(tokens, 0)) + 1 < len(tokens) and tokens[end + 1] == ":":
            tokens = tokens[end + 2 :]
        elif len(tokens) > 1 and tokens[1] == ":" and tokens[0] not in _OPENING:
            tokens = tokens[2:]
        else:
            return tokens
    return tokens


def _name(token: str) -> str:
    return token[1:-1] if token.startswith('"') else token


def _value(tokens: Tokens, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], str]]:
    tokens = _body(tokens)
    if tokens and tokens[0] == "{" and _closing(tokens, 0) == len(tokens) - 1:
        yield from _bindings(tokens[1:-1], path)
    elif len(tokens) == 1:
        yield path, tokens[0]


def _bindings(tokens: Tokens, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], str]]:
    index = 0
    while index < len(tokens):
        end = _until(tokens, index, frozenset({";"}))
        binding = tokens[index:end]
        if binding and binding[0] != "inherit" and "=" in binding:
            equals = binding.index("=")
            names = tuple(_name(word) for word in binding[:equals] if word != ".")
            yield from _value(binding[equals + 1 :], path + names)
        index = end + 1


def attributes(text: str) -> Iterator[tuple[tuple[str, ...], str]]:
    """Each attribute path the module in `text` sets, with its value where that is one word."""
    return _value(_tokens(text), ())


__all__ = ["attributes"]
