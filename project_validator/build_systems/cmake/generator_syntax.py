"""The syntax of generator expressions (see cmake-generator-expressions(7)): text to a `Template` of literal parts and
`Expression`s, without evaluating any (`project_validator.build_systems.cmake.generator_expressions` does).

An expression `$<name:rest>` has a name and, after its first colon outside nested expressions, the rest; both are
templates, since either may hold expressions of its own (`$<$<CONFIG:Debug>:-O0>`). The rest is not split: what a
comma means is the expression's (`$<IF:c,a,b>` takes three arguments, `$<1:a,b>` the value `a,b`), so its evaluation
splits it (`split`). A `$<` never closed is text, as CMake keeps it.
"""

from __future__ import annotations

from dataclasses import dataclass

# What opens an expression.
START = "$<"


@dataclass(frozen=True, slots=True)
class Expression:
    """`$<name:rest>` (`rest` None without a colon), as `written`, from `start` to `end` in the text parsed."""

    name: Template
    rest: Template | None
    written: str
    start: int
    end: int


type Part = str | Expression
type Template = tuple[Part, ...]


def _end(text: str, start: int) -> int:
    """The position of the `>` closing the expression whose content starts at `start`; -1 when it is not closed."""
    depth = 1
    for position in range(start, len(text)):
        if text.startswith(START, position):
            depth += 1
        elif text[position] == ">":
            depth -= 1
            if depth == 0:
                return position
    return -1


def _colon(content: str) -> int:
    """The position of the first colon outside nested expressions in an expression's content; -1 when there is none."""
    depth = 0
    for position, character in enumerate(content):
        if content.startswith(START, position):
            depth += 1
        elif character == ">" and depth:
            depth -= 1
        elif character == ":" and not depth:
            return position
    return -1


def parse(text: str, offset: int = 0) -> Template:
    """The parts of `text`, its literal text and its expressions, each placed from `offset`."""
    parts: list[Part] = []
    position = 0
    while (start := text.find(START, position)) >= 0 and (end := _end(text, start + 2)) >= 0:
        if start > position:
            parts.append(text[position:start])
        content, at = text[start + 2 : end], offset + start + 2
        colon = _colon(content)
        name = parse(content if colon < 0 else content[:colon], at)
        rest = None if colon < 0 else parse(content[colon + 1 :], at + colon + 1)
        parts.append(Expression(name, rest, text[start : end + 1], offset + start, offset + end + 1))
        position = end + 1
    if position < len(text):
        parts.append(text[position:])
    return tuple(parts)


def written(template: Template) -> str:
    """The template's text, as written."""
    return "".join(part if isinstance(part, str) else part.written for part in template)


def split(template: Template, separator: str) -> list[Template]:
    """The template split at `separator` in its literal text, outside the expressions it holds."""
    found: list[list[Part]] = [[]]
    for part in template:
        if isinstance(part, Expression):
            found[-1].append(part)
            continue
        first, *others = part.split(separator)
        found[-1].append(first)
        found += [[other] for other in others]
    return [tuple(piece for piece in pieces if piece != "") for pieces in found]


__all__ = ["START", "Expression", "Part", "Template", "parse", "split", "written"]
