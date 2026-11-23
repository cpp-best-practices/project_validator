"""Whether a Dockerfile is well formed: the instructions it is made of, each one known and given arguments, and a
`FROM` first (after the `ARG`s it may use), read as BuildKit reads them: comments, line continuations (with the
`# escape=` directive's character), the flags of the instructions that take them (`COPY --from=build`, `RUN
--mount=…`), and heredocs (`RUN <<EOF … EOF`), whose bodies are kept with their instruction, never read as
instructions. Each instruction spans the lines it was written on, continuations and heredocs included."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from project_validator.ecosystems.docker import DOCKERFILE
from project_validator.facts.wellformed import ParseError, Parser, decoded
from project_validator.parsing import Span, continued

INSTRUCTIONS = frozenset(
    {
        "ADD",
        "ARG",
        "CMD",
        "COPY",
        "ENTRYPOINT",
        "ENV",
        "EXPOSE",
        "FROM",
        "HEALTHCHECK",
        "LABEL",
        "MAINTAINER",
        "ONBUILD",
        "RUN",
        "SHELL",
        "STOPSIGNAL",
        "USER",
        "VOLUME",
        "WORKDIR",
    }
)
# A parser directive, in the comments before the first instruction: `# syntax=docker/dockerfile:1`, `# escape=\``.
_DIRECTIVE = re.compile(r"^#\s*(?P<key>\w+)\s*=\s*(?P<value>\S+)\s*$")
_HEREDOC = re.compile(r"<<-?\s*(?:\"(?P<quoted>\w+)\"|'(?P<single>\w+)'|(?P<bare>\w+))")


# The instructions that take flags (`--name=value`, or `--name`) before their arguments.
_FLAGGED = frozenset({"ADD", "COPY", "FROM", "HEALTHCHECK", "RUN"})


@dataclass(frozen=True, slots=True)
class Flag:
    """`--name=value`, or `--name` (`value` None)."""

    name: str
    value: str | None


@dataclass(frozen=True, slots=True)
class Heredoc:
    """A heredoc an instruction opens (`<<EOF`, `<<-EOT` strips leading tabs): the lines up to its delimiter."""

    delimiter: str
    body: str
    strip_tabs: bool = False


@dataclass(frozen=True, slots=True)
class Instruction:
    """One instruction, its continuations joined: the keyword as written (upper-cased), its flags, its arguments, and
    the bodies of the heredocs it opens."""

    line: int
    keyword: str
    arguments: str
    flags: tuple[Flag, ...] = ()
    heredocs: tuple[Heredoc, ...] = ()
    span: Span | None = field(default=None, compare=False)


def _comment(text: str) -> bool:
    return text.startswith("#")


def _escape_character(lines: list[str]) -> str:
    """The continuation character the leading `# escape=` directive sets; a backslash without one."""
    for text in lines:
        stripped = text.strip()
        if stripped and not _comment(stripped):
            break
        if (found := _DIRECTIVE.match(stripped)) and found["key"].lower() == "escape":
            return found["value"]
    return "\\"


def _skipped(line: str) -> bool:
    """Whether BuildKit passes over a line between continuations: a blank one, or a comment."""
    stripped = line.strip()
    return not stripped or _comment(stripped)


def _flags(keyword: str, rest: str) -> tuple[tuple[Flag, ...], str]:
    """The flags written first, for an instruction that takes them, and the arguments after them."""
    flags = []
    while keyword in _FLAGGED and rest.startswith("--"):
        word, _, rest = rest.partition(" ")
        name, equals, value = word[2:].partition("=")
        flags.append(Flag(name, value if equals else None))
        rest = rest.lstrip()
    return tuple(flags), rest


def _heredocs(lines: list[str], index: int, arguments: str) -> tuple[tuple[Heredoc, ...], int]:
    """The heredocs `arguments` open (`<<EOF`), each the lines up to one of its delimiter alone, and the index after
    them; one never closed runs to the end of the file."""
    found = []
    for opened in _HEREDOC.finditer(arguments):
        word = opened["quoted"] or opened["single"] or opened["bare"]
        start = index
        while index < len(lines) and lines[index].strip() != word:
            index += 1
        found.append(Heredoc(word, "\n".join(lines[start:index]), strip_tabs=opened[0].startswith("<<-")))
        index = min(index + 1, len(lines))
    return tuple(found), index


def instructions(text: str) -> Iterator[Instruction]:
    """The instructions of a Dockerfile, in order; the keyword of each is upper-cased, known or not."""
    lines = text.splitlines()
    escape = _escape_character(lines)
    # BuildKit continues a line whose escape is followed by spaces; a heredoc body keeps its own (`lines`).
    trimmed = [line.rstrip() for line in lines]
    index = 0
    while index < len(lines):
        if _skipped(lines[index]):
            index += 1
            continue
        first = index + 1
        pieces, index = continued(trimmed, index, escape=escape, skipped=_skipped)
        keyword, _, rest = " ".join(piece.strip() for piece in pieces).strip().partition(" ")
        keyword = keyword.upper()
        flags, arguments = _flags(keyword, rest.strip())
        heredocs: tuple[Heredoc, ...] = ()
        if keyword in ("RUN", "COPY", "ADD"):
            heredocs, index = _heredocs(lines, index, arguments)
        span = Span(first, 1, index, len(lines[index - 1]) + 1)
        yield Instruction(first, keyword, arguments, flags, heredocs, span)


def parse(_path: str, data: bytes) -> None:
    """A Dockerfile is well formed when it has instructions, each known and with arguments, and the first one that
    is not an `ARG` is a `FROM`."""
    found = list(instructions(decoded(data)))
    if not found:
        raise ParseError("no instructions: a Dockerfile starts with FROM")
    for instruction in found:
        if instruction.keyword not in INSTRUCTIONS:
            raise ParseError(f"unknown instruction {instruction.keyword}", instruction.line, 1)
        if not instruction.arguments and not instruction.flags:
            raise ParseError(f"{instruction.keyword} has no arguments", instruction.line, 1)
    stages = [instruction for instruction in found if instruction.keyword != "ARG"]
    if not stages:
        raise ParseError("no build stage: a Dockerfile needs a FROM", found[-1].line, 1)
    if stages[0].keyword != "FROM":
        raise ParseError(f"the first instruction is {stages[0].keyword}, not FROM", stages[0].line, 1)


DOCKERFILE_PARSER = Parser(format=DOCKERFILE, parse=parse)
