"""The Starlark of Bazel's BUILD, MODULE.bazel and WORKSPACE files, read as the rules they call.

A file is a sequence of statements; each top-level call (`cc_test(name = "t", srcs = [...])`, `load(...)`) is a
`Rule`, with its positional arguments and keyword attributes. A value written as a literal (a string, adjacent strings
joined, a number, `True`/`False`/`None`, a list, a dict of them) is read as one; anything computed (a name, a call
such as `glob()` or `select()`, `+`, a comprehension) is `Opaque`, its text kept. Assignments, `def`, `if` and `for`
call no rule at the top level and are passed over. A statement that does not parse is a `Problem`, and the
statements after it are still read.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from project_validator.parsing import Problem, Span


@dataclass(frozen=True, slots=True)
class Opaque:
    """A value computed rather than written as a literal, as written."""

    text: str


type Value = str | int | float | bool | list[Value] | dict[str, Value] | Opaque | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """A top-level call: its function (`cc_test`, `native.cc_library`), its positional arguments and keyword
    attributes, and the line it starts on."""

    kind: str
    arguments: tuple[Value, ...]
    attributes: Mapping[str, Value] = field(default_factory=dict)
    line: int

    @property
    def name(self) -> str | None:
        """Its `name` attribute, when written as a string."""
        name = self.attributes.get("name")
        return name if isinstance(name, str) else None


# A statement starts at a line, outside brackets and strings, that is not indented.
_TOKEN = re.compile(
    r'(?P<string>[rRbB]?(?:"""(?:\\[\s\S]|[^\\])*?"""|\'\'\'(?:\\[\s\S]|[^\\])*?\'\'\'|"(?:\\[\s\S]|[^"\\\n])*"|\'(?:\\[\s\S]|[^\'\\\n])*\'))'
    r"|(?P<comment>#[^\n]*)|(?P<open>[(\[{])|(?P<close>[)\]}])|(?P<newline>\n)|(?P<other>[^\s\"'#()\[\]{}]+|[ \t\r]+)"
)
_CALL = re.compile(r"^(?P<kind>[A-Za-z_][\w.]*)\s*\(", re.DOTALL)
# Mark a statement whose brackets the file never closes, and one that closes a bracket it never opened.
_UNCLOSED, _UNOPENED = "\0", "\1"


def _statements(text: str) -> Iterator[tuple[int, str]]:
    """Each top-level statement, with the line it starts on: the text from an unindented line up to the next newline
    outside brackets; comments are dropped. An indented line belongs to the block above it (`def`, `for`)."""
    depth, start_line, line = 0, 1, 1
    parts: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match[0]
        if match["comment"]:
            continue
        if match["open"]:
            depth += 1
        elif match["close"]:
            if not depth:
                parts.append(_UNOPENED)
            depth = max(depth - 1, 0)
        elif match["newline"] and depth == 0:
            if "".join(parts).strip():
                yield start_line, "".join(parts)
            parts, start_line = [], line + 1
            line += 1
            continue
        line += token.count("\n")
        parts.append(token)
    if "".join(parts).strip():
        yield start_line, "".join(parts) + (_UNCLOSED if depth else "")


def _value(node: ast.expr, text: str) -> Value:
    """A literal as its value; anything else as `Opaque`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, ast.List):
        return [_value(item, text) for item in node.elts]
    if isinstance(node, ast.Dict) and all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys
    ):
        return {key.value: _value(item, text) for key, item in zip(node.keys, node.values, strict=True)}  # type: ignore[union-attr]
    return Opaque(ast.get_source_segment(text, node) or "")


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := _dotted(node.value)) is not None:
        return f"{base}.{node.attr}"
    return None


def _rule(statement: str, line: int) -> Rule | None:
    """The rule a statement calls; None for one that calls none (an assignment, a block, an indented line of one).
    Raises SyntaxError."""
    if not _CALL.match(statement):
        return None
    tree = ast.parse(statement.strip(), mode="eval")
    call = tree.body
    if not isinstance(call, ast.Call) or (kind := _dotted(call.func)) is None:
        return None
    text = statement.strip()
    arguments = tuple(_value(argument, text) for argument in call.args)
    attributes = {keyword.arg: _value(keyword.value, text) for keyword in call.keywords if keyword.arg is not None}
    return Rule(kind=kind, arguments=arguments, attributes=attributes, line=line)


def rules(text: str) -> tuple[list[Rule], tuple[Problem, ...]]:
    """The rules a file calls, in order, and the statements that do not parse."""
    found: list[Rule] = []
    problems: list[Problem] = []
    for line, statement in _statements(text):
        if statement.endswith(_UNCLOSED) or _UNOPENED in statement:
            reason = "a bracket is not closed" if statement.endswith(_UNCLOSED) else "a bracket closes that is not open"
            problems.append(Problem(reason, Span(line)))
            continue
        try:
            rule = _rule(statement, line)
        except (SyntaxError, ValueError, RecursionError) as error:
            problems.append(Problem(f"it does not parse: {getattr(error, 'msg', error)}", Span(line)))
            continue
        if rule is not None:
            found.append(rule)
    return found, tuple(problems)


__all__ = ["Opaque", "Rule", "Value", "rules"]
