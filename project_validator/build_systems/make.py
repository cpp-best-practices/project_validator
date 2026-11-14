"""Make: the recipes `make [target ...]` runs, prerequisites first.

Variables are expanded in the recipes as far as the makefile's assignments (`=`, `:=`, `?=`, `+=`) and the command
line's (`make test FLAGS=-race`) give their values; a recipe whose program is still a variable is unknown. Pattern
rules, conditionals and included makefiles are not followed.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.arguments import positional
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, inside, joined

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
_PROGRAMS = frozenset({"make", "gmake", "mingw32-make"})
_RULE = re.compile(r"^(?P<targets>[^\s:=#][^:=#]*?)\s*::?(?![=])\s*(?P<prerequisites>[^;#]*)(?:;(?P<recipe>.*))?$")
_RECURSIVE_MAKE = re.compile(r"\$[({]MAKE[)}]")
# A variable reference, which make substitutes before the shell splits the line.
VARIABLE = re.compile(r"\$(?:\([^()]*\)|\{[^{}]*\}|[^({$\s])")


@dataclass(slots=True)
class Rule:
    prerequisites: list[str] = field(default_factory=list)
    recipe: list[tuple[int, str]] = field(default_factory=list)


# The variables make itself defines, which a makefile may use without setting.
_BUILT_IN = {
    "CC": "cc",
    "CXX": "g++",
    "CPP": "$(CC) -E",
    "AR": "ar",
    "AS": "as",
    "LD": "ld",
    "RM": "rm -f",
    "FC": "f77",
}


@dataclass(slots=True)
class Makefile:
    rules: dict[str, Rule] = field(default_factory=dict)
    default: str | None = None
    variables: dict[str, str] = field(default_factory=lambda: dict(_BUILT_IN))


# An assignment: `NAME = value`, `:=`, `::=`, `?=`, `+=`, optionally `override` or `export`. `!=` (the shell's output)
# has no value to read.
_ASSIGNMENT = re.compile(
    r"^(?:(?:override|export)\s+)*(?P<name>[A-Za-z_][\w.-]*)\s*(?P<how>\?=|::?=|\+=|=)\s*(?P<value>.*)$"
)
_REFERENCE = re.compile(r"\$(?:\((?P<paren>[A-Za-z_][\w.-]*)\)|\{(?P<brace>[A-Za-z_][\w.-]*)\})")


def _assign(variables: dict[str, str], line: str) -> bool:
    """Record the assignment on `line` in `variables`; whether the line is one."""
    match = _ASSIGNMENT.match(line)
    if match is None:
        return False
    name, how, value = match["name"], match["how"], match["value"].split(" #", 1)[0].strip()
    if how == "?=":
        variables.setdefault(name, value)
    elif how == "+=":
        variables[name] = f"{variables[name]} {value}" if name in variables else value
    else:
        variables[name] = value
    return True


def expand_variables(line: str, variables: dict[str, str]) -> str:
    """`line` with the references to `variables` replaced by their values, which may refer to others in turn; a
    reference to a variable without a value stays as written."""
    for _ in range(10):
        expanded = _REFERENCE.sub(lambda match: variables.get(match["paren"] or match["brace"], match[0]), line)
        if expanded == line:
            break
        line = expanded
    return line


def _recipe_line(line: str) -> str:
    return _RECURSIVE_MAKE.sub("make", line.lstrip("\t").lstrip("@-+ "))


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Each line with its continuations joined, numbered by the line it starts on."""
    start, parts = 0, []
    for number, line in enumerate(text.splitlines(), start=1):
        start = start or number
        if line.endswith("\\"):
            parts.append(line[:-1])
            continue
        yield start, " ".join([*parts, line]) if parts else line
        start, parts = 0, []


def parse_makefile(text: str) -> Makefile:
    """The explicit rules of a makefile, and its default goal (the first target that is not special)."""
    makefile = Makefile()
    current: list[Rule] = []
    for number, line in _logical_lines(text):
        if line.startswith("\t"):
            for rule in current:
                rule.recipe.append((number, _recipe_line(line)))
            continue
        if _assign(makefile.variables, line):
            continue
        match = _RULE.match(line)
        if match is None:
            current = [] if line.strip() and not line.lstrip().startswith("#") else current
            continue
        targets = match["targets"].split()
        current = [makefile.rules.setdefault(target, Rule()) for target in targets]
        for rule in current:
            rule.prerequisites += match["prerequisites"].split()
            if match["recipe"]:
                rule.recipe.append((number, _recipe_line(match["recipe"])))
        if makefile.default is None:
            makefile.default = next((target for target in targets if not target.startswith(".")), None)
    return makefile


def _recipes(makefile: Makefile, path: str, target: str, visited: set[str]) -> Iterator[Script | Unknown]:
    if target in visited or (rule := makefile.rules.get(target)) is None:
        return
    visited.add(target)
    for prerequisite in rule.prerequisites:
        yield from _recipes(makefile, path, prerequisite, visited)
    for number, line in rule.recipe:
        origin = Origin(path=path, at=(target, number))
        # A variable may hold the recipe's prefixes (`Q = @`, then `$(Q)$(CC) …`).
        text = expand_variables(line, makefile.variables).lstrip("@-+ ")
        if (program := _REFERENCE.match(text)) is not None:
            name = program["paren"] or program["brace"]
            yield Unknown(
                origin=origin,
                subject=f"the recipe {text!r}",
                reason=f"its program is the variable {name}, which neither the makefile nor the command line sets",
            )
            continue
        yield Script(text=text, origin=origin, opaque=VARIABLE)


_OPTIONS = frozenset({"-C", "--directory", "-f", "--file", "-j", "--jobs"})


def _directory(command: Command, options: dict[str, str]) -> str:
    """Where make runs: `-C` is relative to the directory the command runs in."""
    return posixpath.normpath(joined(command.directory, options.get("-C") or options.get("--directory") or "."))


def _makefile(context: Context, directory: str, options: dict[str, str]) -> str | None:
    named = options.get("-f") or options.get("--file")
    return found_at(context, directory, [named] if named else MAKEFILES)


def _make_targets(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`make`, `make check`, `make -C build test`: the recipes of the targets, after their prerequisites'."""
    if not command.argv or command.argv[0] not in _PROGRAMS:
        return None
    words, options = positional(command.argv, _OPTIONS)
    if not inside(context, directory := _directory(command, options)):
        return None  # a build tree CI generates, or another checkout: not the project's makefiles
    if (path := _makefile(context, directory, options)) is None:
        return iter((Unknown(origin=command.origin, subject="the makefile", reason="none is found where make runs"),))
    makefile = parse_makefile(context.project.read_text(path))
    for word in words:
        if "=" in word and _ASSIGNMENT.match(word):
            _assign(makefile.variables, word)  # a command-line assignment overrides the makefile's
    goals = [word for word in words if "=" not in word] or ([makefile.default] if makefile.default else [])
    visited: set[str] = set()
    return (script for goal in goals for script in _recipes(makefile, path, goal, visited))


MAKE_TARGETS = CommandExpander(name="Make targets", expand=_make_targets)
