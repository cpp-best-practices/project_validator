"""Whether a Dockerfile is well formed: the instructions it is made of, each one known and given arguments, and a
`FROM` first (after the `ARG`s it may use), read as BuildKit reads them: comments, line continuations (with the
`# escape=` directive's character), and heredocs (`RUN <<EOF … EOF`), whose bodies are not instructions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from project_validator.ecosystems.docker import DOCKERFILE
from project_validator.facts.wellformed import ParseError, Parser, decoded

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


@dataclass(frozen=True, slots=True)
class Instruction:
    """One instruction, its continuations joined: the keyword as written (upper-cased) and its arguments."""

    line: int
    keyword: str
    arguments: str


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


def _joined(lines: list[str], index: int, escape: str) -> tuple[str, int]:
    """The logical line starting at `index`, its continuations joined (blank and comment lines between them skipped),
    and the index after it."""
    text = lines[index].strip()
    index += 1
    while text.endswith(escape):
        text = f"{text[:-1].rstrip()} "
        while index < len(lines) and (not lines[index].strip() or _comment(lines[index].strip())):
            index += 1
        if index == len(lines):
            break
        text += lines[index].strip()
        index += 1
    return text.strip(), index


def _after_heredocs(lines: list[str], index: int, arguments: str) -> int:
    """The index after the bodies of the heredocs `arguments` open (`<<EOF`), each ended by a line of its word."""
    for found in _HEREDOC.finditer(arguments):
        word = found["quoted"] or found["single"] or found["bare"]
        while index < len(lines) and lines[index].strip() != word:
            index += 1
        index += 1
    return min(index, len(lines))


def instructions(text: str) -> Iterator[Instruction]:
    """The instructions of a Dockerfile, in order; the keyword of each is upper-cased, known or not."""
    lines = text.splitlines()
    escape = _escape_character(lines)
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or _comment(stripped):
            index += 1
            continue
        line = index + 1
        joined, index = _joined(lines, index, escape)
        keyword, _, arguments = joined.partition(" ")
        keyword, arguments = keyword.upper(), arguments.strip()
        if keyword in ("RUN", "COPY", "ADD"):
            index = _after_heredocs(lines, index, arguments)
        yield Instruction(line=line, keyword=keyword, arguments=arguments)


def parse(_path: str, data: bytes) -> None:
    """A Dockerfile is well formed when it has instructions, each known and with arguments, and the first one that
    is not an `ARG` is a `FROM`."""
    found = list(instructions(decoded(data)))
    if not found:
        raise ParseError("no instructions: a Dockerfile starts with FROM")
    for instruction in found:
        if instruction.keyword not in INSTRUCTIONS:
            raise ParseError(f"unknown instruction {instruction.keyword}", instruction.line, 1)
        if not instruction.arguments:
            raise ParseError(f"{instruction.keyword} has no arguments", instruction.line, 1)
    stages = [instruction for instruction in found if instruction.keyword != "ARG"]
    if not stages:
        raise ParseError("no build stage: a Dockerfile needs a FROM", found[-1].line, 1)
    if stages[0].keyword != "FROM":
        raise ParseError(f"the first instruction is {stages[0].keyword}, not FROM", stages[0].line, 1)


DOCKERFILE_PARSER = Parser(format=DOCKERFILE, parse=parse)
