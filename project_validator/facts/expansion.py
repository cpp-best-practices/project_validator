"""Command expansion: the commands a command runs in turn, through package scripts, Make targets or hooks.

A `CommandExpander` knows one way a command runs others (`npm test` runs the package's `test` script); an `Action`
knows the command a reusable CI step runs (`psf/black@stable` runs `black --check`). Expanded
commands are facts like those CI runs directly, in the same job, with `via` naming the commands that led to them.
Expansion repeats on what it finds, and stops where a definition would run itself again.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.components import known
from project_validator.evidence import PRE_COMMIT_CONFIGURATION
from project_validator.facts import NOTHING, ActionStep, Command, Fact, Origin, Unknown, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.exit_status import Shell, masked
from project_validator.facts.shell import ShellCommand, Unsplittable, split_script

if TYPE_CHECKING:
    from project_validator.core import Context


@dataclass(frozen=True, slots=True, kw_only=True)
class Script:
    """Shell text that a command runs in turn, where it is defined, and the directory it runs in (when it moves)."""

    text: str
    origin: Origin
    directory: str | None = None
    # Text the shell does not split, because something else substitutes it first (a Make variable).
    opaque: re.Pattern[str] | None = None
    # Whether the text is the whole of a shell script, so that what it sets is seen (a repository's script file,
    # unless it sources another), as a CI step's own script is.
    whole: bool = False
    # The shell that runs the text, when known, which decides whether a command's failure fails it (see `masked`).
    shell: Shell | None = None
    # Why none of the text's commands can fail what runs it (make's `-` before a recipe line), when none can.
    advisory: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Invocation:
    """A command that a command runs in turn, already split: one whose definition is not shell text."""

    argv: tuple[str, ...]
    line: str
    origin: Origin


@dataclass(frozen=True, slots=True, kw_only=True)
class Launched:
    """The command a launcher runs from its own arguments (`bundle exec rake` runs `rake`), where the launcher is,
    with the variables the launcher sets for it (`env CC=clang make`)."""

    argv: tuple[str, ...]
    env: Mapping[str, str] = NOTHING


type Expansion = Script | Invocation | Launched | Unknown
type Expand = Callable[[Command, Context], Iterable[Expansion] | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandExpander:
    """`expand` returns what a command it recognises runs in turn, or None for a command it does not recognise."""

    name: str
    expand: Expand


@dataclass(frozen=True, slots=True, kw_only=True)
class Action:
    """A reusable CI step that runs known commands: `runs` returns them from the step's inputs. `name` is the
    action's repository (`psf/black`), matched without regard to case or version."""

    name: str
    runs: Callable[[Mapping[str, str]], Iterable[tuple[str, ...]]]


def action_commands(step: ActionStep, actions: Iterable[Action]) -> Iterator[Command]:
    """The commands the `step` runs, as the actions that know it say, where the step is (in its `working-directory`
    input, for actions that have one)."""
    repository = step.uses.partition("@")[0].lower()
    for action in actions:
        if action.name.lower() == repository:
            for argv in action.runs(step.inputs):
                yield Command(
                    origin=step.origin,
                    job=step.job,
                    argv=argv,
                    line=f"uses: {step.uses}",
                    directory=step.inputs.get("working-directory") or None,
                    condition=step.condition,
                    advisory=step.advisory,
                )


def script_facts(
    script: str,
    *,
    job: str,
    origin: Origin,
    env: Mapping[str, str] = NOTHING,
    directory: str | None = None,
    condition: str | None = None,
    opaque: re.Pattern[str] | None = None,
    via: tuple[Origin, ...] = (),
    powershell: bool = False,
    whole: bool = False,
    shell: Shell | None = None,
) -> Iterator[Fact]:
    """The commands of a shell script a job runs (see `split_script`, `Script.whole`, and `_judged` for `shell`)."""
    assigned, constants = _seen_assigned(script, whole or not via, powershell=powershell), _Constants(script)
    command = partial(Command, origin=origin, job=job, condition=condition, via=via)
    for found, advisory in _judged(list(split_script(script, opaque, powershell=powershell)), shell):
        if isinstance(found, ShellCommand):
            made = command(
                argv=found.argv,
                line=found.line,
                env={**env, **constants.before(found.line), **dict(found.env)},
                directory=(directory := _changed(directory, found.argv)),
                advisory=advisory,
            )
            yield from _with_program(made, assigned)
        else:
            yield Unknown(origin=origin, subject=f"the command {found.line!r}", reason=found.reason)


def _judged(
    split: list[ShellCommand | Unsplittable], shell: Shell | None
) -> Iterator[tuple[ShellCommand | Unsplittable, str]]:
    """Each of a script's commands with why its failure cannot fail the script in `shell` (see `masked`): "" when it
    can, or when the shell is not known."""
    commands = [found for found in split if isinstance(found, ShellCommand)]
    reasons = iter(masked(commands, shell) if shell is not None else [""] * len(commands))
    return ((found, next(reasons) if isinstance(found, ShellCommand) else "") for found in split)


def advised(facts: Iterable[Fact], advisory: str) -> Iterator[Fact]:
    """`facts` with their commands marked `advisory` (see `Command.advisory`), when it is set."""
    for fact in facts:
        yield replace(fact, advisory=advisory) if advisory and isinstance(fact, Command) else fact


_WHOLE_VARIABLE = re.compile(r"\$(?:\{\w+\}|\w+)")


# What sets a shell variable in a script: an assignment (`export NAME=`), a loop (`for NAME in`), `read NAME`.
_ASSIGNED = re.compile(
    r"(?:^|[;&|(\s])(?:(?:export|local|readonly|declare|typeset)\s+(?:-\w+\s+)*)?(\w+)\+?="
    r"|\bfor\s+(\w+)\s+in\b|\bread\s+(?:-\w+\s+)*(\w+)",
    re.MULTILINE,
)


def _assigned(script: str) -> frozenset[str]:
    return frozenset(name for match in _ASSIGNED.finditer(script) for name in match.groups() if name)


def _seen_assigned(script: str, whole: bool, *, powershell: bool) -> frozenset[str] | None:
    """The variables a script sets, when what it sets is all seen: a whole shell script that sources no other file;
    None otherwise (a script read in part, PowerShell, a script that reads another into itself)."""
    return _assigned(script) if whole and not powershell and not _SOURCES.search(script) else None


# A script that reads another into itself (`. ./env.sh`, `source ci/vars`) may set what is not seen.
_SOURCES = re.compile(r"(?:^|[;&|]\s*)\s*(?:\.|source)\s+\S", re.MULTILINE)
# A line that only sets a variable to plain text, a value the script uses after (`export PREFIX=""`, `TOOL=ruff`).
_CONSTANT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?P<name>[A-Za-z_]\w*)="
    r"(?:\"(?P<double>[^\"$`\\]*)\"|'(?P<single>[^']*)'|(?P<bare>[^\s\"'$`;&|()\\]*))[ \t]*$",
    re.MULTILINE,
)


class _Constants:
    """The variables a script sets once, and only to plain text, each with where it does and the value; asked, line
    by line in order, for those set before each line."""

    def __init__(self, script: str) -> None:
        counts: dict[str, int] = {}
        for match in _ASSIGNED.finditer(script):
            for name in filter(None, match.groups()):
                counts[name] = counts.get(name, 0) + 1
        self.script, self.position, self.found = script, 0, {}
        for match in _CONSTANT.finditer(script):
            if counts.get(match["name"]) == 1:
                value = next(group for group in (match["double"], match["single"], match["bare"]) if group is not None)
                self.found[match["name"]] = (match.end(), value)

    def before(self, line: str) -> dict[str, str]:
        """The constants set before `line`, the next line of the script that runs a command."""
        self.position = max(self.position, self.script.find(line, self.position))
        return {name: value for name, (end, value) in self.found.items() if end <= self.position}


def _with_program(command: Command, assigned: frozenset[str] | None) -> Iterator[Fact]:
    """The command, and, when the name of its program holds a variable neither the job nor the script (whose
    `assigned` variables are known) sets (`$CABAL v2-test`, `$DIR/$TOOL`, `${PREFIX}ruff`), that what runs is unknown;
    a variable in its directory alone (`${HOME}/bin/tool`) still names the program. Only a script seen whole is known
    (None: a script that sources another, or PowerShell, may set what is not seen)."""
    yield command
    argv = resolved(command)
    if argv and _EXPRESSION_NAME.fullmatch(re.split(r"[/\\](?![^{]*\}\})", argv[0])[-1]):
        reason = f"its program is the expression {argv[0]}, whose value is not known"
        yield Unknown(origin=command.origin, subject=f"the command {command.line!r}", reason=reason)
        return
    if assigned is None or not argv or _ASSIGNMENT_WORD.match(argv[0]):
        return
    # A variable the job sets, to a value that cannot be read, is set all the same; `$0` is the script itself.
    name = PurePosixPath(argv[0]).name
    unset = [
        match[0]
        for match in _WHOLE_VARIABLE.finditer(name)
        if match[0].strip("${}") not in {*assigned, *command.env, *_SHELL_SET}
    ]
    if unset:
        named = "is the variable" if unset[0] == name else "is named by the variable"
        reason = f"its program {named} {unset[0]}, which nothing the job runs is seen to set"
        yield Unknown(origin=command.origin, subject=f"the command {command.line!r}", reason=reason)


# What names a program wholly by an expression (`${{ matrix.runs.test }}`), not a file named with one in it.
_EXPRESSION_NAME = re.compile(r"\$\{\{[^{}]*\}\}")
# Variables the shell sets itself: the script's own name, the last argument, the shell's path.
_SHELL_SET = frozenset({"0", "_", "BASH", "SHELL"})


# A word that sets a variable (`tag=${1:?usage: $0 <tag>}`), left whole by the split: it runs no program.
_ASSIGNMENT_WORD = re.compile(r"[A-Za-z_]\w*=")


# Where a CI service checks the project out, written as a variable.
_WORKSPACES = frozenset({"$GITHUB_WORKSPACE", "${GITHUB_WORKSPACE}", "$CI_PROJECT_DIR", "${CI_PROJECT_DIR}"})


def _changed(directory: str | None, argv: tuple[str, ...]) -> str | None:
    """The directory the commands after `argv` run in: `cd` changes it for the rest of the script. A directory a
    variable names (`cd $BUILD_DIR`) is kept as written: it is not known, but most often the project's own build tree.
    One elsewhere (`cd /tmp`, `cd $HOME`, `cd -`, `..` that leaves the project) is outside the project."""
    if argv[:1] != ("cd",) or len(argv) != 2:
        return directory
    target = argv[1].rstrip("/")
    if target in _WORKSPACES or target.split("/", 1)[0] in _WORKSPACES:
        target = target.split("/", 1)[1] if "/" in target else "."
        return posixpath.normpath(target)
    if target.startswith(("$HOME", "${HOME}", "/", "~", "-")):
        return OUTSIDE
    if target.startswith("$"):
        return target
    return posixpath.normpath(joined(directory, target))


# The directory of a command that runs outside the project (`cd /tmp`, `cd $HOME`).
OUTSIDE = "/"


def _children(command: Command, expansion: Expansion) -> Iterator[Fact]:
    via = (*command.via, command.origin)
    if isinstance(expansion, Unknown):
        yield expansion
    elif isinstance(expansion, (Invocation, Launched)):
        found = expansion if isinstance(expansion, Invocation) else command
        yield Command(
            origin=found.origin,
            job=command.job,
            argv=expansion.argv,
            line=found.line,
            env={**command.env, **expansion.env} if isinstance(expansion, Launched) else command.env,
            directory=command.directory,
            condition=command.condition,
            advisory=command.advisory,
            via=via,
        )
    else:
        yield from _script_children(command, expansion, via)


def _script_children(command: Command, script: Script, via: tuple[Origin, ...]) -> Iterator[Fact]:
    commands = script_facts(
        script.text,
        job=command.job,
        origin=script.origin,
        env=command.env,
        directory=script.directory or command.directory,
        condition=command.condition,
        opaque=script.opaque,
        via=via,
        whole=script.whole,
        shell=script.shell,
    )
    yield from advised(commands, command.advisory or script.advisory)


def inside(context: Context, directory: str | None) -> bool:
    """Whether `directory` is one of the project's own (a command elsewhere runs another checkout or a generated build
    tree, whose definitions are not the project's)."""
    if directory in (None, "", "."):
        return True
    if directory.startswith(("/", "..", "$")):
        return False
    return (context.project.root / directory).is_dir()


def expand_command(command: Command, context: Context, expanders: Iterable[CommandExpander]) -> Iterator[Fact]:
    """What `command` runs in turn, through every expander that recognises it, depth first. A command run outside the
    project's own directories is not expanded."""
    if not inside(context, command.directory):
        return
    expanders = tuple(expanders)
    chain = (*command.via, command.origin)
    for expander in expanders:
        expansions = list(expander.expand(command, context) or ())
        if any(isinstance(found, (Script, Invocation)) and found.origin in chain for found in expansions):
            continue  # a definition that runs itself, which is followed once
        # A launcher runs a shorter command than its own, so launching ends.
        expansions = [
            found for found in expansions if not isinstance(found, Launched) or len(found.argv) < len(command.argv)
        ]
        for expansion in expansions:
            for child in _children(command, expansion):
                yield child
                if isinstance(child, Command):
                    yield from expand_command(child, context, expanders)


def expanded(
    facts: Iterable[Fact], context: Context, expanders: Iterable[CommandExpander], actions: Iterable[Action] = ()
) -> Iterator[Fact]:
    """`facts`, each command followed by what it runs in turn, and each action step by the commands it runs (and what
    they run)."""
    expanders, actions = tuple(expanders), tuple(actions)
    for fact in facts:
        yield fact
        if isinstance(fact, Command):
            yield from expand_command(fact, context, expanders)
        elif isinstance(fact, ActionStep):
            for command in action_commands(fact, actions):
                yield command
                yield from expand_command(command, context, expanders)


def from_hook(command: Command) -> bool:
    """Whether `command` runs as a pre-commit hook, which fails when it changes a file."""
    return any(PurePosixPath(origin.path).name in PRE_COMMIT_CONFIGURATION for origin in (*command.via, command.origin))


def known_expanders() -> tuple[CommandExpander, ...]:
    """Every command expander defined by a module of the shared build systems, the shared tools or a profile."""
    return known(CommandExpander)


def known_actions() -> tuple[Action, ...]:
    """Every action defined by a module of the shared build systems, the shared tools or a profile."""
    return known(Action)


_ASSIGNMENT = re.compile(r"([A-Za-z_]\w*)=(.*)", re.DOTALL)


def launcher(
    name: str, prefixes: Iterable[tuple[str, ...]], with_values: frozenset[str] = frozenset(), positionals: int = 0
) -> CommandExpander:
    """An expander of the launchers whose commands start with one of `prefixes` (`("bundle", "exec")`): each runs the
    command its first positional argument starts, with the variables assigned before it (`env CC=clang make`).
    `with_values` are the launcher's options that take a value; `positionals` are the launcher's own positional
    arguments before the command (the duration of `timeout 5m make`).
    """
    starts = tuple(prefixes)

    def expand(command: Command, _: Context) -> list[Expansion] | None:
        argv = resolved(command)
        prefix = starts_with(argv, *starts)
        if prefix is None or len(argv) == len(prefix):
            return None
        return _launched(argv[len(prefix) :], with_values, positionals)

    return CommandExpander(name=name, expand=expand)


def _launched(words: tuple[str, ...], with_values: frozenset[str], positionals: int) -> list[Expansion]:
    rest, env = iter(words), {}
    for word in rest:
        if (assignment := _ASSIGNMENT.fullmatch(word)) is not None:
            env[assignment[1]] = assignment[2]
        elif word == "--" or not word.startswith("-"):
            if positionals and word != "--":
                positionals -= 1
                continue
            launched = (*(() if word == "--" else (word,)), *rest)
            return [Launched(argv=launched, env=env)] if launched else []
        elif word in with_values:
            next(rest, None)
    return []


def found_at(context: Context, directory: str | None, names: Iterable[str]) -> str | None:
    """The first of `names` that exists in `directory`, relative to the project root."""
    return next((path for name in names if context.project.exists(path := joined(directory, name))), None)


def joined(directory: str | None, path: str) -> str:
    """`path` in `directory`, relative to the project root."""
    if directory in (None, "", "."):
        return path
    return f"{directory.strip('/').removeprefix('./')}/{path}"


__all__ = [
    "Action",
    "CommandExpander",
    "Expansion",
    "Invocation",
    "Launched",
    "Script",
    "action_commands",
    "advised",
    "expand_command",
    "expanded",
    "found_at",
    "from_hook",
    "joined",
    "known_actions",
    "known_expanders",
    "launcher",
    "script_facts",
]
