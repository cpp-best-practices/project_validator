"""The CMake language (see cmake-language(7)): a file is a sequence of command invocations, and the block commands
(`if`, `foreach`, `while`, `function`, `macro`, `block`) nest them. Parsing evaluates nothing."""

from __future__ import annotations

import bisect
import enum
import re
from collections.abc import Iterator
from dataclasses import dataclass, field


class Kind(enum.Enum):
    BRACKET = "bracket"  # [[...]]: taken literally
    QUOTED = "quoted"  # "...": one argument, references expanded
    UNQUOTED = "unquoted"  # references expanded, then split into a list


@dataclass(frozen=True, slots=True)
class Argument:
    text: str
    kind: Kind


@dataclass(frozen=True, slots=True)
class Invocation:
    """A command invocation: its name (in lower case, as CMake compares them), arguments and line."""

    name: str
    arguments: tuple[Argument, ...]
    line: int


@dataclass(slots=True)
class Block:
    """A block command: `opening` and the commands in each of its branches, each branch opened by its invocation
    (`if`, then each `elseif` and `else`)."""

    branches: list[tuple[Invocation, list[Node]]] = field(default_factory=list)

    @property
    def opening(self) -> Invocation:
        return self.branches[0][0]


type Node = Invocation | Block


class CMakeSyntaxError(ValueError):
    def __init__(self, line: int, problem: str) -> None:
        super().__init__(f"line {line}: {problem}")
        self.line = line


_TOKEN = re.compile(
    r"""
      (?P<space>[ \t\r\n]+)
    | (?P<bracket_comment>\#\[(?P<comment_level>=*)\[.*?\](?P=comment_level)\])
    | (?P<comment>\#[^\n]*)
    | (?P<open>\()
    | (?P<close>\))
    | (?P<bracket>\[(?P<bracket_level>=*)\[.*?\](?P=bracket_level)\])
    | (?P<quoted>"(?:\\.|[^"\\])*")
    | (?P<unquoted>(?:\\.|"(?:\\.|[^"\\])*"|[^ \t\r\n()\#"\\])+)
    """,
    re.VERBOSE | re.DOTALL,
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Block command -> (the commands that open its later branches, the command that closes it).
BLOCKS = {
    "if": (frozenset({"elseif", "else"}), "endif"),
    "foreach": (frozenset(), "endforeach"),
    "while": (frozenset(), "endwhile"),
    "function": (frozenset(), "endfunction"),
    "macro": (frozenset(), "endmacro"),
    "block": (frozenset(), "endblock"),
}


class _Lines:
    def __init__(self, text: str) -> None:
        self.starts = [0, *(match.end() for match in re.finditer(r"\n", text))]

    def of(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset)


def _tokens(text: str) -> Iterator[tuple[str, str, int]]:
    """(kind, text, offset) of each token that is not blank or a comment."""
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.lastgroup is None:
            raise CMakeSyntaxError(_Lines(text).of(position), f"unexpected {text[position]!r}")
        if match.lastgroup not in ("space", "bracket_comment", "comment"):
            yield match.lastgroup, match[0], position
        position = match.end()


def _argument(kind: str, text: str) -> Argument:
    if kind == "bracket":
        opening = text.index("[", 1) + 1
        content = text[opening : len(text) - opening]
        return Argument(content.removeprefix("\r\n").removeprefix("\n"), Kind.BRACKET)
    if kind == "quoted":
        return Argument(re.sub(r"\\\r?\n", "", text[1:-1]), Kind.QUOTED)
    return Argument(text, Kind.UNQUOTED)


def _arguments(tokens: Iterator[tuple[str, str, int]], lines: _Lines, line: int) -> tuple[Argument, ...]:
    """The arguments up to the closing parenthesis; nested parentheses are arguments of their own (`if((A))`)."""
    found: list[Argument] = []
    depth = 0
    for kind, text, _ in tokens:
        if kind == "close" and depth == 0:
            return tuple(found)
        depth += {"open": 1, "close": -1}.get(kind, 0)
        found.append(Argument(text, Kind.UNQUOTED) if kind in ("open", "close") else _argument(kind, text))
    raise CMakeSyntaxError(line, "the command's arguments are never closed")


def invocations(text: str) -> Iterator[Invocation]:
    """Each command invocation of a CMake file, in order."""
    lines = _Lines(text)
    tokens = _tokens(text)
    for kind, name, offset in tokens:
        line = lines.of(offset)
        if kind != "unquoted" or not _IDENTIFIER.fullmatch(name):
            raise CMakeSyntaxError(line, f"expected a command, found {name!r}")
        if next(tokens, ("", "", 0))[0] != "open":
            raise CMakeSyntaxError(line, f"expected ( after {name}")
        yield Invocation(name.lower(), _arguments(tokens, lines, line), line)


def _block(opening: Invocation, found: Iterator[Invocation]) -> Block:
    later, closing = BLOCKS[opening.name]
    block = Block(branches=[(opening, [])])
    for invocation in found:
        if invocation.name == closing:
            return block
        if invocation.name in later:
            block.branches.append((invocation, []))
        else:
            block.branches[-1][1].append(_node(invocation, found))
    raise CMakeSyntaxError(opening.line, f"{opening.name}() is never closed with {closing}()")


def _node(invocation: Invocation, found: Iterator[Invocation]) -> Node:
    return _block(invocation, found) if invocation.name in BLOCKS else invocation


_CLOSINGS = frozenset(closing for _, closing in BLOCKS.values()) | frozenset({"elseif", "else"})


def parse(text: str) -> list[Node]:
    """The commands of a CMake file, block commands holding those they enclose."""
    found = invocations(text)
    nodes: list[Node] = []
    for invocation in found:
        if invocation.name in _CLOSINGS:
            raise CMakeSyntaxError(invocation.line, f"{invocation.name}() closes nothing")
        nodes.append(_node(invocation, found))
    return nodes


__all__ = ["Argument", "Block", "CMakeSyntaxError", "Invocation", "Kind", "Node", "invocations", "parse"]
