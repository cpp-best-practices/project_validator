"""Make: the recipes `make [target ...]` runs, prerequisites first.

Variables are expanded in the recipes as far as the makefile's assignments (`=`, `:=`, `?=`, `+=`) and the command
line's (`make test FLAGS=-race`) give their values; a recipe whose program is still a variable is unknown. Included
makefiles are followed and pattern rules (`%:`, `lint-%:`) matched to the goals they cover; a goal no rule defines is
unknown. Where make runs in a directory CMake configured in place (`cmake .`), it builds that directory's CMake targets.

The makefile is parsed to a tree (`project_validator.build_systems.make_syntax`) and evaluated here, in order: a
conditional the makefile's variables and the command line decide takes its branch; one that depends on what only the
environment or the system can say (`ifeq ($(OS),Windows_NT)`, `$(shell uname)`) has every branch read, so what CI may
run is not narrowed by a guess.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from project_validator.build_systems import make_syntax
from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.arguments import positional
from project_validator.facts.exit_status import POSIX
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, inside, joined
from project_validator.includes import Chain, Refused, follow
from project_validator.limits import MAKE_INCLUDES

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
_PROGRAMS = frozenset({"make", "gmake", "mingw32-make"})
_RECURSIVE_MAKE = re.compile(r"\$[({]MAKE[)}]")
# A variable reference, which make substitutes before the shell splits the line.
# A `$$` while references are expanded: a `$` the shell sees, never a reference.
_ESCAPED_DOLLAR = "\0"
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
    includes: list[str] = field(default_factory=list)
    # Why an include was not followed (a cycle, the chain too deep), each reported as unknown where make runs.
    problems: list[str] = field(default_factory=list)


_REFERENCE = re.compile(r"\$(?:\((?P<paren>[A-Za-z_][\w.-]*)\)|\{(?P<brace>[A-Za-z_][\w.-]*)\})")


def expand_variables(line: str, variables: dict[str, str]) -> str:
    """`line` with the references to `variables` replaced by their values, which may refer to others in turn; a
    reference to a variable without a value stays as written."""
    for _ in range(10):
        expanded = _REFERENCE.sub(lambda match: variables.get(match["paren"] or match["brace"], match[0]), line)
        if expanded == line:
            break
        line = expanded
    return line


# Why a recipe line written after `-` cannot fail make.
_IGNORED = "make ignores its failure (-)"


def _recipe_line(line: str) -> str:
    """A recipe line as written, with its prefixes (`@`, `-`, `+`): whether make ignores its failure is read later."""
    return _RECURSIVE_MAKE.sub("make", line.lstrip("\t "))


class _Evaluation:
    """A walk over a makefile's tree, in order, as make reads it: variables are set as they are assigned (the command
    line's `overrides` win over the makefile's, unless it says `override`), recipe lines go to the rules written
    before them, and each conditional is decided where it can be (see `_holds`)."""

    def __init__(self, overrides: Mapping[str, str]) -> None:
        self.makefile = Makefile()
        self.makefile.variables.update(overrides)
        self.overrides = frozenset(overrides)
        # The variables whose value the environment cannot change: the command line's, and those the makefile sets
        # outright. make's own defaults (CC is cc), `?=` and `+=` onto a variable not yet set give way to it.
        self.settled = set(overrides)
        self.current: list[Rule] = []

    def nodes(self, nodes: Sequence[make_syntax.Node]) -> None:
        for node in nodes:
            self.node(node)

    def node(self, node: make_syntax.Node) -> None:
        if isinstance(node, make_syntax.RecipeLine):
            for rule in self.current:
                rule.recipe.append((node.span.line, _recipe_line(node.text)))
        elif isinstance(node, make_syntax.Assignment):
            self.assign(node)
        elif isinstance(node, make_syntax.Include):
            self.makefile.includes += expand_variables(node.files, self.makefile.variables).split()
        elif isinstance(node, make_syntax.Rule):
            self.rule(node)
        elif isinstance(node, make_syntax.Conditional):
            self.conditional(node)
        else:
            self.current = []  # any other line ends the recipe before it

    def assign(self, node: make_syntax.Assignment) -> None:
        """Set the variable; `!=` (a shell command's output) has no value to read."""
        variables = self.makefile.variables
        if node.how == "!=" or (node.name in self.overrides and not node.override):
            return
        if node.how == "?=":
            variables.setdefault(node.name, node.value)
        elif node.how == "+=":
            variables[node.name] = f"{variables[node.name]} {node.value}" if node.name in variables else node.value
        else:
            variables[node.name] = node.value
            self.settled.add(node.name)

    def rule(self, node: make_syntax.Rule) -> None:
        makefile = self.makefile
        self.current = [makefile.rules.setdefault(target, Rule()) for target in node.targets]
        for rule in self.current:
            rule.prerequisites += node.prerequisites
            if node.recipe:
                rule.recipe.append((node.span.line, _recipe_line(node.recipe)))
        if makefile.default is None:
            makefile.default = next((target for target in node.targets if not target.startswith(".")), None)

    def conditional(self, node: make_syntax.Conditional) -> None:
        """The first branch that holds; where one cannot be decided, it and every later branch are read."""
        settled = {name: self.makefile.variables[name] for name in self.settled}
        for index, branch in enumerate(node.branches):
            holds = _holds(branch, settled)
            if holds is None:
                for undecided in node.branches[index:]:
                    self.nodes(undecided.body)
                self.nodes(node.otherwise or ())
                return
            if holds:
                self.nodes(branch.body)
                return
        self.nodes(node.otherwise or ())


def _holds(branch: make_syntax.Branch, variables: Mapping[str, str]) -> bool | None:
    """Whether the branch's test holds, from the settled `variables`; None when the makefile and the command line
    cannot say: a variable they do not settle (the environment may set it), or a reference left unexpanded (`$(shell
    uname)`, a function)."""
    if branch.test in ("ifdef", "ifndef"):
        name = _known(branch.arguments.strip(), variables)
        if name is None or name not in variables:
            return None
        return bool(variables[name].strip()) == (branch.test == "ifdef")
    compared = _compared(branch.arguments)
    if compared is None:
        return None
    left, right = (_known(side, variables) for side in compared)
    if left is None or right is None:
        return None
    return (left.strip() == right.strip()) == (branch.test == "ifeq")


def _known(text: str, variables: Mapping[str, str]) -> str | None:
    """`text` with its references expanded, or None when one is left that the variables cannot expand."""
    expanded = expand_variables(text.replace("$$", _ESCAPED_DOLLAR), dict(variables))
    return None if VARIABLE.search(expanded) else expanded.replace(_ESCAPED_DOLLAR, "$")


_QUOTED_PAIR = re.compile(r"""^(?P<q1>["'])(?P<left>.*?)(?P=q1)\s+(?P<q2>["'])(?P<right>.*?)(?P=q2)$""")


def _compared(arguments: str) -> tuple[str, str] | None:
    """The two sides `ifeq` compares: `(a,b)`, split at the comma outside parentheses, or `"a" "b"`."""
    arguments = arguments.strip()
    if (quoted := _QUOTED_PAIR.match(arguments)) is not None:
        return quoted["left"], quoted["right"]
    if not (arguments.startswith("(") and arguments.endswith(")")):
        return None
    inner, depth = arguments[1:-1], 0
    for index, character in enumerate(inner):
        depth += {"(": 1, "{": 1, ")": -1, "}": -1}.get(character, 0)
        if character == "," and depth == 0:
            return inner[:index], inner[index + 1 :]
    return None


def parse_makefile(text: str, overrides: Mapping[str, str] | None = None) -> Makefile:
    """The rules of a makefile, its variables and includes, and its default goal (the first target that is not
    special), as make reads it with the command line's `overrides`."""
    evaluation = _Evaluation(overrides or {})
    evaluation.nodes(make_syntax.parse(text).nodes)
    return evaluation.makefile


def _rule(makefile: Makefile, target: str) -> tuple[Rule, str] | None:
    """The rule that builds `target`, and its stem: an explicit one, else the first pattern rule (`%:`, `lint-%:`)
    whose pattern matches it."""
    if (rule := makefile.rules.get(target)) is not None:
        return rule, ""
    for pattern, rule in makefile.rules.items():
        prefix, percent, suffix = pattern.partition("%")
        long_enough = len(target) > len(prefix) + len(suffix)
        if percent and long_enough and target.startswith(prefix) and target.endswith(suffix):
            return rule, target[len(prefix) : len(target) - len(suffix)]
    return None


def _recipes(makefile: Makefile, path: str, target: str, visited: set[str]) -> Iterator[Script | Unknown]:
    if target in visited or (found := _rule(makefile, target)) is None:
        return
    visited.add(target)
    rule, stem = found
    for prerequisite in rule.prerequisites:
        yield from _recipes(makefile, path, prerequisite.replace("%", stem), visited)
    automatic = {**makefile.variables, "@": target, "*": stem}
    for number, line in rule.recipe:
        origin = Origin(path=path, at=(target, number))
        # A variable may hold the recipe's prefixes (`Q = @`, then `$(Q)$(CC) …`).
        # `$$` is a `$` the shell sees, never a reference (Documenter's `$$(biome_jll.biome())`).
        line = line.replace("$$", _ESCAPED_DOLLAR).replace("$@", target).replace("$*", stem)
        expanded = expand_variables(line, automatic)
        unprefixed = expanded.lstrip("@-+ ")
        text = unprefixed.replace(_ESCAPED_DOLLAR, "$")
        ignored = _IGNORED if "-" in expanded[: len(expanded) - len(unprefixed)] else ""
        if (program := _REFERENCE.match(text)) is not None:
            name = program["paren"] or program["brace"]
            yield Unknown(
                origin=origin,
                subject=f"the recipe {text!r}",
                reason=f"its program is the variable {name}, which neither the makefile nor the command line sets",
            )
            continue
        # Each recipe line is a shell script of its own, run by `sh -c`.
        yield Script(text=text, origin=origin, opaque=VARIABLE, shell=POSIX, advisory=ignored)


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
    goals = [word for word in words if "=" not in word]
    if (path := _makefile(context, directory, options)) is None:
        return _configured_by_cmake(command, context, directory, goals)
    overrides = {found["name"]: found["value"] for word in words if (found := make_syntax.ASSIGNMENT.match(word))}
    makefile = _read(context, path, overrides)
    goals = goals or ([makefile.default] if makefile.default else [])
    return _goals(makefile, path, goals, command)


def _read(context: Context, path: str, overrides: Mapping[str, str]) -> Makefile:
    """The makefile at `path`, with the rules and variables of the makefiles it includes that the project holds, and
    of those they include in turn (see `project_validator.includes`); its own win over theirs."""
    makefile = parse_makefile(context.project.read_text(path), overrides)
    _include(context, makefile, posixpath.dirname(path), Chain.start(path), overrides)
    return makefile


def _include(context: Context, makefile: Makefile, directory: str, chain: Chain, overrides: Mapping[str, str]) -> None:
    """Merge into `makefile` what its includes define; make finds an included file from where it runs (`directory`).
    One the project does not hold is passed over silently: a generated `-include deps.d` is usual."""
    for name in makefile.includes:
        found = follow(chain, posixpath.normpath(joined(directory, name)), MAKE_INCLUDES, context.project.exists)
        if isinstance(found, Refused):
            if not found.missing:
                makefile.problems.append(found.reason)
            continue
        other = parse_makefile(context.project.read_text(found.paths[-1]), overrides)
        _include(context, other, directory, found, overrides)
        makefile.rules = {**other.rules, **makefile.rules}
        makefile.variables = {**other.variables, **makefile.variables}
        makefile.problems += other.problems


def _goals(makefile: Makefile, path: str, goals: list[str], command: Command) -> Iterator[Expansion]:
    for problem in dict.fromkeys(makefile.problems):
        yield Unknown(origin=command.origin, subject=f"the includes of {path}", reason=problem)
    visited: set[str] = set()
    for goal in goals:
        if _rule(makefile, goal) is None:
            reason = "no rule of the makefile (or of the makefiles it includes) builds it"
            yield Unknown(origin=command.origin, subject=f"the make target {goal}", reason=reason)
            continue
        yield from _recipes(makefile, path, goal, visited)


def _configured_by_cmake(command: Command, context: Context, directory: str, goals: list[str]) -> Iterator[Expansion]:
    """Where no makefile is found but CMake configures the directory in place (`cmake .`), make builds its CMake
    targets (the makefile is CMake's, generated); elsewhere, what make runs is unknown."""
    lists = joined(directory, "CMakeLists.txt")
    if not context.project.exists(lists):
        yield Unknown(origin=command.origin, subject="the makefile", reason="none is found where make runs")
        return
    for goal in goals or ["all"]:
        yield Script(text=f"cmake --build {directory} --target {goal}", origin=Origin(path=lists, at=(goal,)))


MAKE_TARGETS = CommandExpander(name="Make targets", expand=_make_targets)
