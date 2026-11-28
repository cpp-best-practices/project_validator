"""Make: the recipes `make [target ...]` runs, prerequisites first.

Variables are expanded in the recipes as far as the makefile's assignments (`=`, `:=`, `?=`, `+=`) and the command
line's (`make test FLAGS=-race`) give their values; a recipe whose program is still a variable is unknown. Included
makefiles are followed and pattern rules (`%:`, `lint-%:`) matched to the goals they cover; a goal no rule defines is
unknown. Where make runs in a directory CMake configured in place (`cmake .`), it builds that directory's CMake targets.

The makefile is parsed to a tree (`project_validator.build_systems.make_syntax`) and evaluated here, in order, each
line in the builds it is read in (a `Condition`). A conditional the makefile's variables and the command line decide
takes its branch. One on the platform (`ifeq ($(OS),Windows_NT)`, `$(shell uname -s)`) has each branch read on the
platforms it holds on, and one on what else only the environment can say (`ifdef DEBUG`, `ifeq ($(CC),clang)`) has
each read behind that requirement, so what CI may run is not narrowed by a guess. A variable set in branches takes
each value in the builds its branch holds in, and so does a recipe line: a job follows those that may hold on its
runner (see `project_validator.facts.expansion.Only`).
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from project_validator.build_systems import make_syntax
from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown, whole_environment
from project_validator.facts.arguments import positional
from project_validator.facts.conditions import (
    ALWAYS,
    MOST_CHOICES,
    NEVER,
    Choices,
    Condition,
    assigned,
    both,
    combined,
    either,
    negated,
    only,
    requiring,
)
from project_validator.facts.exit_status import POSIX
from project_validator.facts.expansion import CommandExpander, Expansion, Only, Script, found_at, inside, joined
from project_validator.includes import Chain, Refused, follow
from project_validator.limits import MAKE_INCLUDES
from project_validator.parsing import Span
from project_validator.templates import Reference, Syntax

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
_PROGRAMS = frozenset({"make", "gmake", "mingw32-make"})
_RECURSIVE_MAKE = re.compile(r"\$[({]MAKE[)}]")
# A variable reference, which make substitutes before the shell splits the line.
# A `$$` while references are expanded: a `$` the shell sees, never a reference.
_ESCAPED_DOLLAR = "\0"
VARIABLE = re.compile(r"\$(?:\([^()]*\)|\{[^{}]*\}|[^({$\s])")


@dataclass(frozen=True, slots=True)
class Step:
    """A line of a recipe: where it is written, its text, and the builds it is read in."""

    span: Span
    text: str
    when: Condition = ALWAYS


@dataclass(slots=True)
class Rule:
    """A target's prerequisites and recipe, each in the builds it is written in."""

    prerequisites: Choices[str] = field(default_factory=list)
    recipe: list[Step] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Setting:
    """A value a variable is set to, and whether it is `settled`: the environment cannot change it (the command
    line's, or one the makefile sets outright); make's own defaults (CC is cc), `?=` and `+=` onto a variable not yet
    set give way to the environment."""

    text: str
    settled: bool = True


type Variables = dict[str, Choices[Setting]]


# The variables make itself defines, which a makefile may use without setting.
_DEFAULTS = {
    "CC": "cc",
    "CXX": "g++",
    "CPP": "$(CC) -E",
    "AR": "ar",
    "AS": "as",
    "LD": "ld",
    "RM": "rm -f",
    "FC": "f77",
}


def _built_in() -> Variables:
    return {name: [(Setting(value, settled=False), ALWAYS)] for name, value in _DEFAULTS.items()}


# The variables a CI runner sets that a job does not (upstream #361): where a makefile tests one, what it runs is
# required of the run. Every CI service sets CI, to true.
_RUNNER_VARIABLES = re.compile(
    r"(?:GITHUB|RUNNER|GITLAB|CI|TRAVIS|CIRCLE|APPVEYOR|CIRRUS|BUILDKITE|DRONE|BITBUCKET|AGENT|BUILD|SYSTEM)_\w*"
    r"|OS|HOME|PATH|USER|PWD|TMPDIR|LANG|TERM|HOSTNAME"
)
_CI = {"CI": "true"}


def _environment(environment: Mapping[str, str]) -> Variables:
    """What a job's `environment` settles: its variables, CI, and make's own defaults it does not change."""
    return {name: [(Setting(value), ALWAYS)] for name, value in {**_DEFAULTS, **_CI, **environment}.items()}


@dataclass(slots=True)
class Makefile:
    rules: dict[str, Rule] = field(default_factory=dict)
    default: str | None = None
    variables: Variables = field(default_factory=_built_in)
    includes: list[str] = field(default_factory=list)
    # Why an include was not followed (a cycle, the chain too deep), each reported as unknown where make runs.
    problems: list[str] = field(default_factory=list)


# A reference to a variable by name, `$(NAME)` or `${NAME}`; `VARIABLE` is anything make substitutes.
_REFERENCE = Syntax(re.compile(r"\$(?:\((?P<name>[A-Za-z_][\w.-]*)\)|\{(?P<name_brace>[A-Za-z_][\w.-]*)\})"))


type _Lookup = Callable[[Reference], Choices[str] | None]


def _lookup(variables: Variables, *, settled: bool = False) -> _Lookup:
    """The values of `variables`, each in its builds (only the `settled` ones, when asked); in the builds a variable
    has no such value, a reference to it stays as written."""

    def values(reference: Reference) -> Choices[str] | None:
        found = [
            (setting.text, when)
            for setting, when in variables.get(reference.name, ())
            if setting.settled or not settled
        ]
        if not found:
            return None
        rest = negated(either(*(when for _, when in found)))
        return [*found, *([(reference.written, rest)] if rest else [])]

    return values


def _expanded(text: str, lookup: _Lookup, inside: frozenset[str] = frozenset()) -> Choices[str]:
    """The texts `text` takes, its references replaced by each of their values, expanded in turn, in the builds it
    takes each; a reference whose name is computed (`$(verbose_$(V))`) is expanded once its name is. A reference
    inside the value of the variable it names (or of one that value refers to) stays as written: make rejects a
    variable that refers to itself, and substituting it again would double it each time."""
    parts: list[Choices[str]] = []
    names = set(inside)
    for part in _REFERENCE.parse(text).parts:
        if isinstance(part, str):
            parts.append([(part, ALWAYS)])
        elif part.name in inside or (values := lookup(part)) is None:
            parts.append([(part.written, ALWAYS)])
        else:
            names.add(part.name)
            parts.append(_within(values, lookup, inside | {part.name}))
    joined = [(_called("".join(chosen)), when) for chosen, when in combined(*parts)]
    # Each pass that substitutes guards more names, so expanding again ends.
    return joined if names == inside else _within(joined, lookup, frozenset(names))


def _within(values: Choices[str], lookup: _Lookup, inside: frozenset[str]) -> Choices[str]:
    """Each of `values` expanded (see `_expanded`), in the builds both it and its expansion are in."""
    expanded = (
        (new, held)
        for value, when in values
        for new, other in _expanded(value, lookup, inside)
        if (held := both(when, other))
    )
    return list(expanded)[:MOST_CHOICES]


# A call of one of make's text functions whose arguments hold no reference left: `$(filter %.c,a.c b.h)`.
_FUNCTION = re.compile(
    r"\$\((?P<name>filter|filter-out|findstring|strip|addprefix|addsuffix|subst|patsubst|if|or|and)"
    r" (?P<arguments>[^$()]*)\)"
)


def _if(arguments: list[str]) -> str:
    """`$(if condition,then[,else])`: `then` where the condition is not empty (once stripped), else `else`."""
    condition, then, otherwise = (*arguments, "", "")[:3]
    return then if condition.strip() else otherwise


def _and(arguments: list[str]) -> str:
    """`$(and a,b,...)`: the last argument when none is empty (once stripped), else empty."""
    return arguments[-1] if all(argument.strip() for argument in arguments) else ""


# make's conditional functions (upstream #361: argo-cd's `$(if $(GOFLAGS),,ALL)`): `or` is its first argument that is
# not empty.
_CONDITIONALS: dict[str, Callable[[list[str]], str]] = {
    "if": _if,
    "or": lambda arguments: next((argument for argument in arguments if argument.strip()), ""),
    "and": _and,
}


def _called(text: str) -> str:
    """`text` with each text function whose arguments are known replaced by its result, innermost first."""
    while (found := _FUNCTION.search(text)) is not None:
        text = text[: found.start()] + _result(found["name"], found["arguments"]) + text[found.end() :]
    return text


def _result(name: str, arguments: str) -> str:
    """What `$(name arguments)` gives: `strip` collapses whitespace, `findstring` is its first argument when the
    second holds it, `filter` and `filter-out` keep the words of the second that match (or do not) a pattern of the
    first, where `%` matches any text; `addprefix` and `addsuffix` put the first before or after each word of the
    second (nvm's `$(addprefix test-,$(SHELLS))`), `subst` replaces text and `patsubst` the words a pattern matches;
    `if`, `or` and `and` as `_CONDITIONALS` says."""
    if name == "strip":
        return " ".join(arguments.split())
    if name in _CONDITIONALS:
        return _CONDITIONALS[name](arguments.split(","))
    if name in ("subst", "patsubst"):
        found, _, rest = arguments.partition(",")
        replacement, _, text = rest.partition(",")
        if name == "subst":
            return text.replace(found, replacement)
        return " ".join(_substituted(word, found, replacement) for word in text.split())
    first, _, second = arguments.partition(",")
    if name == "addprefix":
        return " ".join(first + word for word in second.split())
    if name == "addsuffix":
        return " ".join(word + first for word in second.split())
    if name == "findstring":
        return first if first in second else ""
    patterns = first.split()
    return " ".join(word for word in second.split() if any(map(_matches(word), patterns)) == (name == "filter"))


def _substituted(word: str, pattern: str, replacement: str) -> str:
    """A word as `patsubst` gives it: the replacement, with the text `%` matched in the pattern in place of its `%`,
    when the pattern matches the word; else the word."""
    prefix, percent, suffix = pattern.partition("%")
    if not percent:
        return replacement if word == pattern else word
    if not _matches(word)(pattern):
        return word
    stem = word[len(prefix) : len(word) - len(suffix)]
    return replacement.replace("%", stem, 1) if "%" in replacement else replacement


def _matches(word: str) -> Callable[[str], bool]:
    def matches(pattern: str) -> bool:
        prefix, percent, suffix = pattern.partition("%")
        if not percent:
            return word == pattern
        return len(word) >= len(prefix) + len(suffix) and word.startswith(prefix) and word.endswith(suffix)

    return matches


def _choices(text: str, lookup: _Lookup) -> Choices[str]:
    """`text` expanded in each build (see `_expanded`); the builds that give the same text are one choice."""
    merged: dict[str, Condition] = {}
    for value, when in _expanded(text, lookup):
        merged[value] = either(merged.get(value, NEVER), when)
    return list(merged.items())


# Why a recipe line written after `-` cannot fail make.
_IGNORED = "make ignores its failure (-)"


def _recipe_line(line: str) -> str:
    """A recipe line as written, with its prefixes (`@`, `-`, `+`): whether make ignores its failure is read later."""
    return _RECURSIVE_MAKE.sub("make", line.lstrip("\t "))


class _Evaluation:
    """A walk over a makefile's tree, in order, as make reads it, each line in the builds `when` names: variables are
    set as they are assigned (the command line's `overrides` win over the makefile's, unless it says `override`),
    recipe lines go to the rules written before them, and each branch of a conditional is read where it holds (see
    `_Test`)."""

    def __init__(self, overrides: Mapping[str, str], environment: Mapping[str, str] | None = None) -> None:
        self.makefile = Makefile()
        if environment is not None:
            self.makefile.variables.update(_environment(environment))
        self.makefile.variables.update({name: [(Setting(value), ALWAYS)] for name, value in overrides.items()})
        # Whether the job's environment is known: a variable nothing sets is then empty (see `_Test`).
        self.settles = environment is not None
        self.overrides = frozenset(overrides)
        self.current: list[Rule] = []
        self.when = ALWAYS

    def nodes(self, nodes: Sequence[make_syntax.Node]) -> None:
        for node in nodes:
            self.node(node)

    def node(self, node: make_syntax.Node) -> None:
        if isinstance(node, make_syntax.RecipeLine):
            for rule in self.current:
                rule.recipe.append(Step(node.span, _recipe_line(node.text), self.when))
        elif isinstance(node, make_syntax.Assignment):
            self.assign(node)
        elif isinstance(node, make_syntax.Include):
            lookup = _lookup(self.makefile.variables)
            self.makefile.includes += [name for files, _ in _choices(node.files, lookup) for name in files.split()]
        elif isinstance(node, make_syntax.Rule):
            self.rule(node)
        elif isinstance(node, make_syntax.Conditional):
            self.conditional(node)
        else:
            self.current = []  # any other line ends the recipe before it

    def assign(self, node: make_syntax.Assignment) -> None:
        """Set the variable in the builds the assignment is read in; `!=` (a shell command's output) has no value to
        read."""
        variables = self.makefile.variables
        if node.how == "!=" or (node.name in self.overrides and not node.override):
            return
        old = variables.get(node.name, [])
        unset = both(self.when, negated(either(*(when for _, when in old))))
        # With the job's environment known, a variable it does not set is not set: `?=` and `+=` settle it.
        if node.how == "?=":
            variables[node.name] = list(old)
            if unset:
                variables[node.name].append((Setting(node.value, settled=self.settles), unset))
        elif node.how == "+=":
            appended = [(Setting(f"{setting.text} {node.value}", setting.settled), when) for setting, when in old]
            variables[node.name] = assigned(old, appended, self.when)
            if unset:
                variables[node.name].append((Setting(node.value, settled=self.settles), unset))
        else:
            variables[node.name] = assigned(old, [(Setting(node.value), ALWAYS)], self.when)

    def rule(self, node: make_syntax.Rule) -> None:
        makefile = self.makefile
        targets = [name for target in node.targets for name in self._names(target)]
        self.current = [makefile.rules.setdefault(target, Rule()) for target in targets]
        for rule in self.current:
            rule.prerequisites += [
                (name, self.when) for prerequisite in node.prerequisites for name in self._names(prerequisite)
            ]
            if node.recipe:
                rule.recipe.append(Step(node.span, _recipe_line(node.recipe), self.when))
        if makefile.default is None:
            makefile.default = next((target for target in targets if not target.startswith(".")), None)

    def _names(self, target: str) -> list[str]:
        """The rules a target or prerequisite names: itself, or, as make expands a rule's targets and prerequisites
        when it reads them, the words its references give with the variables set so far (nvm's `$(SHELL_TARGETS):`,
        pyenv's `test-docker: $(TEST_UNIT_DOCKER_PREFIX)`), in any build; as written while one is left unexpanded."""
        if "$" not in target:
            return [target]
        expanded = _Test(self.makefile.variables).expanded(target)
        names = list(dict.fromkeys(word for value, _ in expanded for word in value.split()))
        return names if names and not any("$" in name for name in names) else [target]

    def conditional(self, node: make_syntax.Conditional) -> None:
        """Each branch, read in the builds where it holds and no branch before it does; what none holds in, after."""
        remaining = self.when
        for branch in node.branches:
            holds = _Test(self.makefile.variables, settles=self.settles).holds(branch)
            self.within(both(remaining, holds), branch.body)
            remaining = both(remaining, negated(holds))
        self.within(remaining, node.otherwise or ())

    def within(self, when: Condition, nodes: Sequence[make_syntax.Node]) -> None:
        if not when:
            return  # a branch that holds in no build is not read
        outer, self.when = self.when, when
        self.nodes(nodes)
        self.when = outer


class _Test:
    """Where a conditional's test holds, from the settled values of `variables`. What the makefile and the command
    line cannot say (a variable they do not settle, a reference left unexpanded, `$(shell uname)`) holds behind a
    requirement, or, where it names the platform, on the platforms it holds on (see `_platform`)."""

    def __init__(self, variables: Variables, *, settles: bool = False) -> None:
        self.variables = variables
        self.settled = _lookup(variables, settled=True)
        self.settles = settles

    def empty(self, name: str) -> bool:
        """Whether a variable nothing sets is empty: with the job's environment known, all but a runner's own."""
        return self.settles and not _RUNNER_VARIABLES.fullmatch(name)

    def lookup(self, reference: Reference) -> Choices[str] | None:
        found = self.settled(reference)
        return [("", ALWAYS)] if found is None and self.empty(reference.name) else found

    def holds(self, branch: make_syntax.Branch) -> Condition:
        positive = branch.test in ("ifdef", "ifeq")
        held = self.defined(branch.arguments.strip()) if branch.test in ("ifdef", "ifndef") else self.equal(branch)
        return held if positive else negated(held)

    def defined(self, written: str) -> Condition:
        """Where the variable `written` names has a value that is not empty (make does not expand it to say)."""
        found: list[Condition] = []
        for name, when in self.expanded(written):
            settled = [(setting, held) for setting, held in self.variables.get(name, ()) if setting.settled]
            decided = either(*(held for _, held in settled))
            nonempty = either(*(held for setting, held in settled if setting.text.strip()))
            unknown = NEVER if self.empty(name) else both(negated(decided), requiring(f"defined {name}"))
            found.append(both(when, either(nonempty, unknown)))
        return either(*found)

    def equal(self, branch: make_syntax.Branch) -> Condition:
        compared = _compared(branch.arguments)
        if compared is None:
            return requiring(branch.arguments.strip())
        left, right = (self.expanded(side) for side in compared)
        return either(*(both(when, _equal(*sides)) for sides, when in combined(left, right)))

    def expanded(self, text: str) -> Choices[str]:
        """`text` expanded in each build, its `$$` kept apart (see `_ESCAPED_DOLLAR`), and stripped."""
        return [(value.strip(), when) for value, when in _choices(text.replace("$$", _ESCAPED_DOLLAR), self.lookup)]


def _equal(left: str, right: str) -> Condition:
    """Where two expanded texts are equal: in every build or none, when neither holds a reference left unexpanded."""
    if not VARIABLE.search(left) and not VARIABLE.search(right):
        return ALWAYS if left == right else NEVER
    platform = _platform(left, right)
    return platform if platform is not None else requiring(f"{left} == {right}")


# What `uname -s` prints on each platform: Windows's are MSYS2's, Cygwin's and MinGW's.
_UNAME = re.compile(r"\$[({]shell\s+uname(?:\s+-s)?\s*[)}]")
_UNAME_PLATFORMS = {"Linux": "linux", "Darwin": "macos"}
_WINDOWS_UNAME = ("MINGW", "MSYS", "CYGWIN")


def _platform(left: str, right: str) -> Condition | None:
    """Where one side names the platform and the other is plain text: `$(OS)`, which Windows sets to Windows_NT (and
    others leave empty), or what `$(shell uname -s)` prints. None for any other comparison."""
    for probe, text in ((left, right), (right, left)):
        if VARIABLE.search(text):
            continue
        if probe in ("$(OS)", "${OS}") and text in ("Windows_NT", ""):
            windows = only("platforms", ["windows"])
            return windows if text else negated(windows)
        if _UNAME.fullmatch(probe):
            if text.startswith(_WINDOWS_UNAME):
                return only("platforms", ["windows"])
            return only("platforms", [_UNAME_PLATFORMS[text]]) if text in _UNAME_PLATFORMS else None
    return None


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


def parse_makefile(
    text: str, overrides: Mapping[str, str] | None = None, environment: Mapping[str, str] | None = None
) -> Makefile:
    """The rules of a makefile, its variables and includes, and its default goal (the first target that is not
    special), as make reads it with the command line's `overrides`, in a job's `environment` when it is known."""
    evaluation = _Evaluation(overrides or {}, environment)
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


def _recipes(
    makefile: Makefile, path: str, target: str, visited: set[str], when: Condition = ALWAYS
) -> Iterator[Expansion]:
    """The recipe lines `target` runs in the builds `when` names, after its prerequisites', each line once in each
    of the texts its variables give it, in the builds it takes it in."""
    if target in visited or (found := _rule(makefile, target)) is None:
        return
    visited.add(target)
    rule, stem = found
    for prerequisite, written in rule.prerequisites:
        if held := both(when, written):
            yield from _recipes(makefile, path, prerequisite.replace("%", stem), visited, held)
    lookup = _lookup(makefile.variables)
    for step in rule.recipe:
        origin = Origin(path=path, at=(target,), span=step.span)
        # A variable may hold the recipe's prefixes (`Q = @`, then `$(Q)$(CC) …`).
        # `$$` is a `$` the shell sees, never a reference (Documenter's `$$(biome_jll.biome())`).
        line = step.text.replace("$$", _ESCAPED_DOLLAR).replace("$@", target).replace("$*", stem)
        yield from _step(_choices(line, lookup), origin, both(when, step.when))


def _step(texts: Choices[str], origin: Origin, when: Condition) -> Iterator[Expansion]:
    """A recipe line, in the builds `when` names, in each of the `texts` it takes: a shell script in each, but, where
    its program is still a variable, one unknown, in every build any of those texts is in."""
    unknown: Unknown | None = None
    unknown_in = NEVER
    for expanded, chosen in texts:
        if held := both(when, chosen):
            recipe = _recipe(expanded, origin)
            if isinstance(recipe, Script):
                yield _only(recipe, held)
                continue
            unknown, unknown_in = unknown or recipe, either(unknown_in, held)
    if unknown is not None:
        yield _only(unknown, unknown_in)


def _only(expansion: Script | Unknown, when: Condition) -> Expansion:
    return expansion if when == ALWAYS else Only(expansion, when)


def _recipe(expanded: str, origin: Origin) -> Script | Unknown:
    """A recipe line, expanded: the shell script it runs, or, when its program is still a variable, that what it runs
    is unknown."""
    unprefixed = expanded.lstrip("@-+ ")
    text = unprefixed.replace(_ESCAPED_DOLLAR, "$")
    ignored = _IGNORED if "-" in expanded[: len(expanded) - len(unprefixed)] else ""
    if (program := _REFERENCE.parse(text).leading) is not None:
        return Unknown(
            origin=origin,
            subject=f"the recipe {text!r}",
            reason=f"its program is the variable {program.name}, which neither the makefile nor the command line sets",
        )
    # Each recipe line is a shell script of its own, run by `sh -c`.
    return Script(text=text, origin=origin, opaque=VARIABLE, shell=POSIX, advisory=ignored)


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
    # The command line's assignments, and MAKECMDGOALS, the goals as written (none when it names none).
    assigned = {found["name"]: found["value"] for word in words if (found := make_syntax.ASSIGNMENT.match(word))}
    overrides = {"MAKECMDGOALS": " ".join(goals), **assigned}
    makefile = _read(context, path, overrides, command.env if whole_environment(command) else None)
    goals = goals or ([makefile.default] if makefile.default else [])
    return _goals(makefile, path, goals, command)


def _read(context: Context, path: str, overrides: Mapping[str, str], environment: Mapping[str, str] | None) -> Makefile:
    """The makefile at `path`, with the rules and variables of the makefiles it includes that the project holds, and
    of those they include in turn (see `project_validator.includes`); its own win over theirs. It is read in the
    job's `environment`, when it is all the job sets (see `whole_environment`)."""
    makefile = parse_makefile(context.project.read_text(path), overrides, environment)
    _include(context, makefile, posixpath.dirname(path), Chain.start(path), overrides, environment)
    return makefile


def _include(
    context: Context,
    makefile: Makefile,
    directory: str,
    chain: Chain,
    overrides: Mapping[str, str],
    environment: Mapping[str, str] | None,
) -> None:
    """Merge into `makefile` what its includes define; make finds an included file from where it runs (`directory`).
    One the project does not hold is passed over silently: a generated `-include deps.d` is usual."""
    for name in makefile.includes:
        found = follow(chain, posixpath.normpath(joined(directory, name)), MAKE_INCLUDES, context.project.exists)
        if isinstance(found, Refused):
            if not found.missing:
                makefile.problems.append(found.reason)
            continue
        other = parse_makefile(context.project.read_text(found.paths[-1]), overrides, environment)
        _include(context, other, directory, found, overrides, environment)
        makefile.rules = {**other.rules, **makefile.rules}
        makefile.variables = {**other.variables, **makefile.variables}
        makefile.problems += other.problems


# The targets PostgreSQL's PGXS defines for an extension (`include $(PGXS)`, the makefile `pg_config --pgxs` names,
# which the project does not hold): what they run is the make command itself, which the test runners know
# (`installcheck` runs pg_regress, `prove_installcheck` the TAP tests).
_PGXS_TARGETS = frozenset(
    {
        "all",
        "install",
        "uninstall",
        "installdirs",
        "clean",
        "installcheck",
        "prove_installcheck",
        "prove_check",
        "check",
    }
)


def _from_pgxs(makefile: Makefile, goal: str) -> bool:
    """Whether PGXS, which the makefile includes, defines the target `goal`."""
    return goal in _PGXS_TARGETS and any("--pgxs" in word for word in makefile.includes)


def _goals(makefile: Makefile, path: str, goals: list[str], command: Command) -> Iterator[Expansion]:
    for problem in dict.fromkeys(makefile.problems):
        yield Unknown(origin=command.origin, subject=f"the includes of {path}", reason=problem)
    visited: set[str] = set()
    for goal in goals:
        if _rule(makefile, goal) is None and _from_pgxs(makefile, goal):
            continue
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
