"""Command expansion: the commands a command runs in turn, through package scripts, Make targets or hooks.

A `CommandExpander` knows one way a command runs others (`npm test` runs the package's `test` script); an `Action`
knows the command a reusable CI step runs (`psf/black@stable` runs `black --check`). Expanded
commands are facts like those CI runs directly, in the same job, with `via` naming the commands that led to them.
Expansion repeats on what it finds, and stops where a definition would run itself again.
"""

import posixpath
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.evidence import PRE_COMMIT_CONFIGURATION
from project_validator.facts import NOTHING, ActionStep, Command, Fact, Origin, Unknown, resolved
from project_validator.facts.arguments import program
from project_validator.facts.shell import ShellCommand, split_script

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
) -> Iterator[Fact]:
    """The commands of a shell script a job runs (PowerShell when `powershell`), a line that cannot be split as unknown;
    `opaque` matches the expressions a CI service evaluates before the shell runs (see `split_script`)."""
    for found in split_script(script, opaque, powershell=powershell):
        if isinstance(found, ShellCommand):
            directory = _changed(directory, found.argv)
            yield Command(
                origin=origin,
                job=job,
                argv=found.argv,
                line=found.line,
                env={**env, **dict(found.env)},
                directory=directory,
                condition=condition,
                via=via,
            )
        else:
            yield Unknown(origin=origin, subject=f"the command {found.line!r}", reason=found.reason)


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
            via=via,
        )
    else:
        yield from script_facts(
            expansion.text,
            job=command.job,
            origin=expansion.origin,
            env=command.env,
            directory=expansion.directory or command.directory,
            condition=command.condition,
            opaque=expansion.opaque,
            via=via,
        )


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
    from project_validator.components import known

    return known(CommandExpander)


def known_actions() -> tuple[Action, ...]:
    """Every action defined by a module of the shared build systems, the shared tools or a profile."""
    from project_validator.components import known

    return known(Action)


_ASSIGNMENT = re.compile(r"([A-Za-z_]\w*)=(.*)", re.DOTALL)


def launcher(
    name: str, prefixes: Iterable[tuple[str, ...]], with_values: frozenset[str] = frozenset()
) -> CommandExpander:
    """An expander of the launchers whose commands start with one of `prefixes` (`("bundle", "exec")`): each runs the
    command its first positional argument starts, with the variables assigned before it (`env CC=clang make`).
    `with_values` are the launcher's options that take a value.
    """
    starts = tuple(prefixes)

    def expand(command: Command, _: Context) -> list[Expansion] | None:
        argv = resolved(command)
        prefix = next((start for start in starts if _starts_with(argv, start)), None)
        return None if prefix is None else _launched(argv[len(prefix) :], with_values)

    return CommandExpander(name=name, expand=expand)


def _launched(words: tuple[str, ...], with_values: frozenset[str]) -> list[Expansion]:
    rest, env = iter(words), {}
    for word in rest:
        if (assignment := _ASSIGNMENT.fullmatch(word)) is not None:
            env[assignment[1]] = assignment[2]
        elif word == "--" or not word.startswith("-"):
            launched = (*(() if word == "--" else (word,)), *rest)
            return [Launched(argv=launched, env=env)] if launched else []
        elif word in with_values:
            next(rest, None)
    return []


def _starts_with(argv: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(argv) > len(prefix) and program(argv) == prefix[0] and argv[1 : len(prefix)] == prefix[1:]


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
