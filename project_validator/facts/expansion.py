"""Command expansion: the commands a command runs in turn, through package scripts, Make targets or hooks.

A `CommandExpander` knows one way a command runs others (`npm test` runs the package's `test` script). Expanded
commands are facts like those CI runs directly, in the same job, with `via` naming the commands that led to them.
Expansion repeats on what it finds, and stops where a definition would run itself again.
"""

import importlib
import pkgutil
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING

from project_validator.facts import NOTHING, Command, Fact, Origin, Unknown
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


type Expansion = Script | Invocation | Unknown
type Expand = Callable[[Command, Context], Iterable[Expansion] | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandExpander:
    """`expand` returns what a command it recognises runs in turn, or None for a command it does not recognise."""

    name: str
    expand: Expand


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
) -> Iterator[Fact]:
    """The commands of a shell script a job runs; a line that cannot be split is recorded as unknown.

    `opaque` matches the expressions a CI service evaluates before the shell runs (see `split_script`).
    """
    for found in split_script(script, opaque):
        if isinstance(found, ShellCommand):
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


def _children(command: Command, expansion: Expansion) -> Iterator[Fact]:
    via = (*command.via, command.origin)
    if isinstance(expansion, Unknown):
        yield expansion
    elif isinstance(expansion, Invocation):
        yield Command(
            origin=expansion.origin,
            job=command.job,
            argv=expansion.argv,
            line=expansion.line,
            env=command.env,
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


def expand_command(command: Command, context: Context, expanders: Iterable[CommandExpander]) -> Iterator[Fact]:
    """What `command` runs in turn, through every expander that recognises it, depth first."""
    expanders = tuple(expanders)
    chain = (*command.via, command.origin)
    for expander in expanders:
        expansions = list(expander.expand(command, context) or ())
        if any(not isinstance(found, Unknown) and found.origin in chain for found in expansions):
            continue  # a definition that runs itself, which is followed once
        for expansion in expansions:
            for child in _children(command, expansion):
                yield child
                if isinstance(child, Command):
                    yield from expand_command(child, context, expanders)


def expanded(facts: Iterable[Fact], context: Context, expanders: Iterable[CommandExpander]) -> Iterator[Fact]:
    """`facts`, each command followed by what it runs in turn."""
    expanders = tuple(expanders)
    for fact in facts:
        yield fact
        if isinstance(fact, Command):
            yield from expand_command(fact, context, expanders)


# The packages whose modules may define command expanders, besides the profiles.
_PACKAGES = ("project_validator.build_systems", "project_validator.tools")


def _modules() -> Iterator[ModuleType]:
    from project_validator.ecosystems import PROFILES

    for package_name in _PACKAGES:
        package = importlib.import_module(package_name)
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda module: module.name):
            yield importlib.import_module(f"{package_name}.{info.name}")
    for name in PROFILES:
        yield importlib.import_module(f"project_validator.ecosystems.{name}")


def built_in_expanders() -> tuple[CommandExpander, ...]:
    """Every command expander defined by a module of the shared build systems, the shared tools or a profile."""
    found = (value for module in _modules() for value in vars(module).values())
    return tuple(dict.fromkeys(value for value in found if isinstance(value, CommandExpander)))


def positional(argv: tuple[str, ...], with_values: frozenset[str] = frozenset()) -> tuple[list[str], dict[str, str]]:
    """The positional arguments after the program, and the values of the options in `with_values`.

    `--opt=value` and `--opt value` are both read; other options are skipped.
    """
    words: list[str] = []
    options: dict[str, str] = {}
    arguments = iter(argv[1:])
    for word in arguments:
        name, equals, value = word.partition("=")
        if name in with_values:
            options[name] = value if equals else next(arguments, "")
        elif not word.startswith("-"):
            words.append(word)
    return words, options


def found_at(context: Context, directory: str | None, names: Iterable[str]) -> str | None:
    """The first of `names` that exists in `directory`, relative to the project root."""
    return next((path for name in names if context.project.exists(path := joined(directory, name))), None)


def joined(directory: str | None, path: str) -> str:
    """`path` in `directory`, relative to the project root."""
    if directory in (None, "", "."):
        return path
    return f"{directory.strip('/').removeprefix('./')}/{path}"


__all__ = [
    "CommandExpander",
    "Expansion",
    "Invocation",
    "Script",
    "built_in_expanders",
    "expand_command",
    "expanded",
    "found_at",
    "joined",
    "positional",
    "script_facts",
]
