"""pixi: the tasks `pixi run <task> [argument ...]` runs, dependencies first, or the program it runs in the project's
environment when the word is no task (`pixi run pytest`) (typst-fletcher).

A task is defined in `[tasks]` of pixi.toml (or `[tool.pixi.tasks]` of pyproject.toml), a feature's
(`[feature.<name>.tasks]`) or a platform's (`[target.<platform>.tasks]`). It is a command, or a table: its `cmd` (a
string, or a list of words), the tasks it `depends-on` (names, or `{ task = name }`), the `cwd` it runs in (from the
manifest's directory), and its `args` (names, or `{ arg = name, default = value }`), which the command line's
arguments fill and `{{ name }}` interpolates. A task without `args` takes the command line's arguments after its
command. A task runs in the manifest's directory (or its `cwd`), wherever pixi runs; a task whose argument is left
unset is unknown.
"""

from __future__ import annotations

import posixpath
import re
import shlex
import tomllib
from collections.abc import Iterator, Mapping

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.expansion import CommandExpander, Expansion, Launched, Script, found_at, inside, joined

_MANIFESTS = ("pixi.toml", "pyproject.toml")
_WITH_VALUES = frozenset({"-e", "--environment", "--manifest-path", "--color", "--executable"})
_INTERPOLATION = re.compile(r"\{\{\s*(?P<name>[\w-]+)\s*\}\}")

type Tasks = dict[str, Mapping[str, object]]


def _table(value: object, *keys: str) -> Mapping[str, object]:
    for key in keys:
        value = value.get(key) if isinstance(value, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _task(value: object) -> Mapping[str, object] | None:
    """A task as a table: a command alone is its `cmd`."""
    if isinstance(value, (str, list)):
        return {"cmd": value}
    return value if isinstance(value, Mapping) else None


def parse_tasks(path: str, text: str) -> Tasks:
    """The tasks of a pixi manifest: the project's, then each feature's and each platform's (the first definition of a
    name wins); empty when it does not parse."""
    try:
        document: Mapping[str, object] = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    if path.endswith("pyproject.toml"):
        document = _table(document, "tool", "pixi")
    scopes = [document, *_table(document, "feature").values()]
    tables = [table for scope in scopes for table in (scope, *_table(scope, "target").values())]
    tasks: Tasks = {}
    for table in tables:
        for name, value in _table(table, "tasks").items():
            if (task := _task(value)) is not None:
                tasks.setdefault(name, task)
    return tasks


def _manifest(context: Context, command: Command, named: str | None) -> str | None:
    """The named manifest, or the first pixi.toml (or pyproject.toml with pixi's table) where pixi runs or above."""
    if named:
        return found_at(context, command.directory, [named])
    directory = posixpath.normpath(command.directory or ".")
    while True:
        for name in _MANIFESTS:
            found = found_at(context, None if directory == "." else directory, [name])
            if found is not None and (name == "pixi.toml" or "[tool.pixi" in context.project.read_text(found)):
                return found
        if directory in ("", "."):
            return None
        directory = posixpath.dirname(directory) or "."


def _words(argv: tuple[str, ...]) -> tuple[list[str], str | None]:
    """The words after `pixi run` and its options, and the manifest it names."""
    words: list[str] = []
    manifest, rest = None, iter(argv[2:])
    for word in rest:
        if words:
            words.append(word)
            continue
        name, equals, value = word.partition("=")
        if name in _WITH_VALUES:
            value = value if equals else next(rest, "")
            manifest = value if name == "--manifest-path" else manifest
        elif word == "--" or not word.startswith("-"):
            words.extend(() if word == "--" else (word,))
    return words, manifest


def _argument(declared: object) -> tuple[str, str | None] | None:
    """An `args` entry's name and default: `"name"`, or `{ arg = "name", default = "value" }`."""
    if isinstance(declared, str):
        return declared, None
    if isinstance(declared, Mapping) and isinstance(name := declared.get("arg"), str):
        default = declared.get("default")
        return name, default if isinstance(default, str) else None
    return None


def _arguments(task: Mapping[str, object], given: list[str]) -> dict[str, str | None] | None:
    """The values of the task's `args`, the given ones first, then their defaults; None for a task without args."""
    declared = task.get("args")
    if not isinstance(declared, list):
        return None
    arguments = [found for entry in declared if (found := _argument(entry)) is not None]
    return {name: given[index] if index < len(given) else default for index, (name, default) in enumerate(arguments)}


def _command(task: Mapping[str, object], given: list[str]) -> str | bool | None:
    """The task's command with its arguments; False for a task with none (an alias), None when one is unset."""
    cmd = task.get("cmd")
    if isinstance(cmd, list):
        cmd = " ".join(word for word in cmd if isinstance(word, str))
    if not isinstance(cmd, str):
        return False
    values = _arguments(task, given)
    if values is None:
        return " ".join((cmd, *(shlex.quote(word) for word in given)))
    missing = False

    def value(match: re.Match[str]) -> str:
        nonlocal missing
        found = values.get(match["name"])
        missing = missing or found is None
        return found or ""

    text = _INTERPOLATION.sub(value, cmd)
    return None if missing else text


def _dependency(entry: object) -> str | None:
    """A `depends-on` entry's task: `"name"`, or `{ task = "name", args = [...] }` (whose args are not read)."""
    if isinstance(entry, Mapping):
        entry = entry.get("task")
    return entry if isinstance(entry, str) else None


def _dependencies(task: Mapping[str, object]) -> list[str]:
    found = task.get("depends-on", task.get("depends_on", []))
    entries = [found] if isinstance(found, str) else found if isinstance(found, list) else []
    return [name for entry in entries if (name := _dependency(entry)) is not None]


def _run(tasks: Tasks, path: str, name: str, given: list[str], visited: set[str]) -> Iterator[Script | Unknown]:
    if name in visited or name not in tasks:
        return
    visited.add(name)
    task = tasks[name]
    for dependency in _dependencies(task):
        yield from _run(tasks, path, dependency, [], visited)
    text = _command(task, given)
    origin = Origin(path=path, at=("tasks", name))
    if text is None:
        yield Unknown(origin=origin, subject=f"the pixi task {name}", reason="an argument it interpolates is not set")
    elif isinstance(text, str):
        # A task runs in the manifest's directory, or in its `cwd` from there.
        cwd, home = task.get("cwd"), posixpath.dirname(path) or None
        yield Script(text=text, origin=origin, directory=joined(home, cwd) if isinstance(cwd, str) else home or ".")


def _pixi_run(command: Command, context: Context) -> Iterator[Expansion] | None:
    argv = resolved(command)
    if not starts_with(argv, ("pixi", "run")) or not inside(context, command.directory):
        return None
    words, named = _words(argv)
    if not words:
        return None
    path = _manifest(context, command, named)
    tasks = parse_tasks(path, context.project.read_text(path)) if path else {}
    if words[0] not in tasks:
        return iter((Launched(argv=tuple(words)),))  # a program, run in the environment
    return _run(tasks, str(path), words[0], words[1:], set())


PIXI_TASKS = CommandExpander(name="pixi tasks", expand=_pixi_run)
