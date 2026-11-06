"""Make: the recipes `make [target ...]` runs, prerequisites first.

Rules are read as written: variables are not expanded (except `$(MAKE)`, which runs make again), and pattern rules,
conditionals and included makefiles are not followed.
"""

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


@dataclass(slots=True)
class Makefile:
    rules: dict[str, Rule] = field(default_factory=dict)
    default: str | None = None


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


def _recipes(makefile: Makefile, path: str, target: str, visited: set[str]) -> Iterator[Script]:
    if target in visited or (rule := makefile.rules.get(target)) is None:
        return
    visited.add(target)
    for prerequisite in rule.prerequisites:
        yield from _recipes(makefile, path, prerequisite, visited)
    for number, line in rule.recipe:
        yield Script(text=line, origin=Origin(path=path, at=(target, number)), opaque=VARIABLE)


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
    goals = [word for word in words if "=" not in word] or ([makefile.default] if makefile.default else [])
    visited: set[str] = set()
    return (script for goal in goals for script in _recipes(makefile, path, goal, visited))


MAKE_TARGETS = CommandExpander(name="Make targets", expand=_make_targets)
