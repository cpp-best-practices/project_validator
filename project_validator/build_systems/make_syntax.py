"""The syntax of a makefile: its lines to a tree of nodes with spans, without consulting any variable.

`parse` reads assignments (`=`, `:=`, `::=`, `?=`, `+=`, `!=`, with `override` and `export`, and `define … endef`),
rules, recipe lines, includes and conditionals (`ifeq`, `ifneq`, `ifdef`, `ifndef`, with `else` chains), each with the
lines it spans. A recipe line is a node of its own: which rule it belongs to (the one written before it, through any
conditional) is decided where the tree is evaluated, `project_validator.build_systems.make`, as variables and which
branch a conditional takes are. Any other line (`vpath %.c src`, `export NAME`) is a `Directive`, which ends the
recipe before it, as make reads it; comments and blank lines are not nodes.

A makefile make would reject is read as far as it goes: a conditional or `define` never closed ends with the makefile,
and an `else` or `endif` that closes nothing is passed over; each is reported in `Makefile.errors`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from project_validator.parsing import ParseError, Span, continued

# An assignment: `NAME = value`, `:=`, `::=`, `?=`, `+=` or `!=`, optionally after `override` or `export`.
ASSIGNMENT = re.compile(
    r"^(?P<modifiers>(?:(?:override|export)\s+)*)(?P<name>[A-Za-z_][\w.-]*)\s*(?P<how>\?=|::?=|\+=|!=|=)\s*(?P<value>.*)$"
)
_DEFINE = re.compile(
    r"^(?P<modifiers>(?:(?:override|export)\s+)*)define\s+(?P<name>[A-Za-z_][\w.-]*)\s*(?P<how>\?=|::?=|\+=|=)?\s*$"
)
_RULE = re.compile(
    r"^(?P<targets>[^\s:=#][^:=#]*?)\s*(?P<colons>::?)(?![=])\s*(?P<prerequisites>[^;#]*)(?:;(?P<recipe>.*)|\s*#.*)?$"
)
_INCLUDE = re.compile(r"^(?P<optional>-|s)?include\s+(?P<files>.+)$")
_CONDITIONAL = re.compile(r"^(?P<test>ifeq|ifneq|ifdef|ifndef)(?:\s+(?P<arguments>.*?))?\s*$")
_ELSE = re.compile(r"^else(?:\s+(?P<rest>.*?))?\s*$")


@dataclass(frozen=True, slots=True)
class Assignment:
    name: str
    how: str
    value: str
    span: Span
    override: bool = False
    export: bool = False


@dataclass(frozen=True, slots=True)
class Rule:
    """`targets: prerequisites`, with the recipe written after a `;` on the same line (`recipe`, or empty)."""

    targets: tuple[str, ...]
    prerequisites: tuple[str, ...]
    recipe: str
    span: Span
    double_colon: bool = False


@dataclass(frozen=True, slots=True)
class RecipeLine:
    """A line of a recipe, as written after its tab (its continuations joined)."""

    text: str
    span: Span


@dataclass(frozen=True, slots=True)
class Include:
    """`include files` (`-include` or `sinclude`: `optional`), the files as written, before expansion."""

    files: str
    optional: bool
    span: Span


@dataclass(frozen=True, slots=True)
class Branch:
    """`test arguments` (`ifeq ($(CC),gcc)`, `ifdef DEBUG`) and the nodes read when it holds."""

    test: str
    arguments: str
    body: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class Conditional:
    """Its branches, tried in order (`ifeq …`, then each `else ifdef …`), and what is read when none holds."""

    branches: tuple[Branch, ...]
    otherwise: tuple[Node, ...] | None
    span: Span


@dataclass(frozen=True, slots=True)
class Directive:
    """A line that is none of the others (`vpath %.c src`, `export NAME`), as written."""

    text: str
    span: Span


type Node = Assignment | Rule | RecipeLine | Include | Conditional | Directive


@dataclass(frozen=True, slots=True)
class Makefile:
    nodes: tuple[Node, ...]
    errors: tuple[ParseError, ...] = ()


@dataclass(slots=True)
class _Open:
    """A conditional being read: its branches so far, the nodes of the one being read, and its `else`."""

    test: str
    line: int
    branches: list[Branch] = field(default_factory=list)
    body: list[Node] = field(default_factory=list)
    otherwise: list[Node] | None = None
    pending: tuple[str, str] = ("", "")

    def close_branch(self) -> None:
        if self.otherwise is None:
            self.branches.append(Branch(*self.pending, tuple(self.body)))
            self.body = []

    def nodes(self) -> list[Node]:
        return self.body if self.otherwise is None else self.otherwise


class _Parser:
    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.index = 0
        self.top: list[Node] = []
        self.open: list[_Open] = []
        self.errors: list[ParseError] = []

    def add(self, node: Node) -> None:
        (self.open[-1].nodes() if self.open else self.top).append(node)

    def parse(self) -> Makefile:
        while self.index < len(self.lines):
            first = self.index + 1
            pieces, self.index = continued(self.lines, self.index)
            span = Span(first, 1, self.index, len(pieces[-1]) + 1)
            if pieces[0].startswith("\t"):
                self.add(RecipeLine(" ".join(pieces).lstrip("\t "), span))
            else:
                self.line(" ".join(pieces), span)
        last = len(self.lines)
        end = Span(last, 1, last, len(self.lines[-1]) + 1) if self.lines else Span(1)
        for found in reversed(self.open):
            self.errors.append(ParseError(f"the {found.test} is never closed with endif", found.line))
            self.close(end)
        return Makefile(tuple(self.top), tuple(self.errors))

    def line(self, line: str, span: Span) -> None:
        """A line that is not a recipe line; what a conditional holds is often indented, which make ignores."""
        line = line.lstrip()
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            return
        if self.directive(stripped, span):
            return
        if (found := _DEFINE.match(stripped)) is not None:
            self.add(self.define(found, span))
        elif (found := ASSIGNMENT.match(line)) is not None:
            value = found["value"].split(" #", 1)[0].strip()
            self.add(Assignment(found["name"], found["how"], value, span, *_modifiers(found["modifiers"])))
        elif (found := _INCLUDE.match(line)) is not None:
            self.add(Include(found["files"].split(" #", 1)[0].strip(), found["optional"] is not None, span))
        elif (found := _RULE.match(line)) is not None:
            targets, prerequisites = tuple(found["targets"].split()), tuple(found["prerequisites"].split())
            self.add(Rule(targets, prerequisites, (found["recipe"] or "").lstrip("\t "), span, found["colons"] == "::"))
        else:
            self.add(Directive(stripped, span))

    def directive(self, line: str, span: Span) -> bool:
        """A conditional's opening, `else` or `endif`: read into the open conditionals."""
        if (found := _CONDITIONAL.match(line)) is not None:
            self.open.append(_Open(found["test"], span.line, pending=(found["test"], found["arguments"] or "")))
            return True
        if (found := _ELSE.match(line)) is not None:
            self.otherwise(found["rest"] or "", span)
            return True
        if line == "endif" or line.startswith(("endif ", "endif\t", "endif#")):
            if not self.open:
                self.errors.append(ParseError("endif closes nothing", span.line))
            else:
                self.close(span)
            return True
        return False

    def otherwise(self, rest: str, span: Span) -> None:
        """`else`, or `else ifeq …`, which opens another branch of the same conditional."""
        if not self.open:
            self.errors.append(ParseError("else closes nothing", span.line))
            return
        found = self.open[-1]
        if found.otherwise is not None:
            self.errors.append(ParseError(f"the {found.test} has a second else", span.line))
            return
        found.close_branch()
        if (chained := _CONDITIONAL.match(rest)) is not None:
            found.pending = (chained["test"], chained["arguments"] or "")
        else:
            found.otherwise = []

    def close(self, end: Span) -> None:
        """Close the innermost conditional, which ends where `end` (its `endif`, or the makefile's last line) does."""
        found = self.open.pop()
        found.close_branch()
        otherwise = None if found.otherwise is None else tuple(found.otherwise)
        self.add(Conditional(tuple(found.branches), otherwise, Span(found.line, 1, end.end_line, end.end_column)))

    def define(self, found: re.Match[str], span: Span) -> Assignment:
        """`define NAME` … `endef`: the lines between are the value, never read as rules or assignments."""
        body: list[str] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            self.index += 1
            if line.strip() == "endef" or line.strip().startswith("endef "):
                break
            body.append(line)
        else:
            self.errors.append(ParseError("the define is never closed with endef", span.line))
        whole = Span(span.line, 1, self.index, len(self.lines[self.index - 1]) + 1)
        return Assignment(found["name"], found["how"] or "=", "\n".join(body), whole, *_modifiers(found["modifiers"]))


def _modifiers(written: str) -> tuple[bool, bool]:
    """Whether `override` and `export` are among the modifiers written before an assignment."""
    words = written.split()
    return "override" in words, "export" in words


def parse(text: str) -> Makefile:
    """The tree of a makefile's text; what make would reject is read as far as it goes and reported."""
    return _Parser(text).parse()


__all__ = [
    "Assignment",
    "Branch",
    "Conditional",
    "Directive",
    "Include",
    "Makefile",
    "Node",
    "RecipeLine",
    "Rule",
    "parse",
]
