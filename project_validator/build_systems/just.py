"""just: the recipes `just [recipe [argument ...] ...]` runs, dependencies first (cetz, busted, hledger).

A justfile's recipes are `name parameters: dependencies` followed by an indented body, each line run by the shell
(`@` and `-` prefixes dropped, a trailing `\\` continuing a line). `{{name}}` interpolates a variable (`name :=
"value"`, or one the command line sets: `just name=value recipe`) or a parameter (the command line's arguments, else
the parameter's default; a `*` or `+` parameter takes the rest). Without a recipe, just runs the first. A recipe
whose body is a script for another interpreter (a `#!` line other than a shell's), or whose interpolation is
computed (`env_var(...)`, backticks), is unknown, as is a recipe the justfile does not define.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at, inside, joined

JUSTFILES = ("justfile", "Justfile", ".justfile", "JUSTFILE")
_RECIPE = re.compile(r"^@?(?P<name>[A-Za-z_][\w-]*)(?P<parameters>(?:\s+[^:]*?)?)\s*:(?!=)(?P<dependencies>.*)$")
_ASSIGNMENT = re.compile(r"^(?:export\s+)?(?P<name>[A-Za-z_][\w-]*)\s*:=\s*(?P<value>.*)$")
_STRING = re.compile(r"""^(?:"(?P<double>[^"\\]*)"|'(?P<single>[^']*)')\s*(?:#.*)?$""")
# A variable the command line sets: `just gallery_dir=docs gallery`.
_OVERRIDE = re.compile(r"[A-Za-z_][\w-]*=.*")
_INTERPOLATION = re.compile(r"\{\{\s*(?P<expression>[^{}]*?)\s*\}\}")
_SHELLS = re.compile(r"^#!\s*(?:/usr)?/bin/(?:env\s+)?(?:ba|z|da)?sh\b")
# The options that print rather than run (`just --list`), and those that take a value.
_INFORMATION = frozenset({"-l", "--list", "--summary", "--dump", "--evaluate", "--show", "-s", "--choose", "--fmt"})
_WITH_VALUES = frozenset({"-f", "--justfile", "-d", "--working-directory", "--shell", "--dotenv-filename"})


@dataclass(slots=True)
class Recipe:
    line: int
    parameters: list[tuple[str, str | None, bool]] = field(default_factory=list)  # name, default, variadic
    dependencies: list[str] = field(default_factory=list)
    body: list[tuple[int, str]] = field(default_factory=list)


@dataclass(slots=True)
class Justfile:
    recipes: dict[str, Recipe] = field(default_factory=dict)
    # A variable whose value is not a plain string (`env_var(...)`, a backtick) is None.
    variables: dict[str, str | None] = field(default_factory=dict)


def _string(value: str) -> str | None:
    found = _STRING.match(value.strip())
    return None if found is None else (found["double"] if found["double"] is not None else found["single"])


def _parameter(word: str) -> tuple[str, str | None, bool]:
    variadic = word[:1] in "*+"
    name, equals, default = word.lstrip("*+$").partition("=")
    return name, (_string(default) if equals else ("" if word[:1] == "*" else None)), variadic


def _dependencies(text: str) -> list[str]:
    """The recipes a recipe depends on: names, or `(name arguments)` (whose arguments are not read)."""
    text = text.partition("#")[0].replace("&&", " ")
    return [match[1] or match[2] for match in re.finditer(r"\(\s*([\w-]+)[^)]*\)|([\w-]+)", text)]


def parse_justfile(text: str) -> Justfile:
    justfile, recipe = Justfile(), None
    lines = text.splitlines()
    number = 0
    while number < len(lines):
        line = lines[number]
        number += 1
        if recipe is not None and line[:1] in (" ", "\t"):
            while line.endswith("\\") and number < len(lines):
                line = line[:-1] + " " + lines[number].strip()
                number += 1
            recipe.body.append((number, line.strip()))
            continue
        if not line.strip():
            continue
        recipe = None
        if line.startswith(("#", "[", "set ", "alias ", "import ", "mod ")):
            continue
        if (assignment := _ASSIGNMENT.match(line)) is not None:
            justfile.variables[assignment["name"]] = _string(assignment["value"])
        elif (found := _RECIPE.match(line)) is not None:
            recipe = Recipe(
                line=number,
                parameters=[_parameter(word) for word in found["parameters"].split()],
                dependencies=_dependencies(found["dependencies"]),
            )
            justfile.recipes.setdefault(found["name"], recipe)
    return justfile


def _interpolated(text: str, values: dict[str, str | None]) -> str | None:
    """`text` with each `{{name}}` replaced; None when one is computed or unset."""
    missing = False

    def value(match: re.Match[str]) -> str:
        nonlocal missing
        found = values.get(match["expression"])
        if found is None:
            missing = True
            return ""
        return found

    replaced = _INTERPOLATION.sub(value, text)
    return None if missing else replaced


def _body(recipe: Recipe, name: str, path: str, values: dict[str, str | None]) -> Iterator[Script | Unknown]:
    lines = recipe.body
    if lines and lines[0][1].startswith("#!"):
        if not _SHELLS.match(lines[0][1]):
            reason = f"its body is a {lines[0][1][2:].strip()} script"
            yield Unknown(origin=Origin(path=path, at=(name,)), subject=f"the just recipe {name}", reason=reason)
            return
        lines = lines[1:]
    for number, line in lines:
        text = _interpolated(line, values)
        if text is None:
            reason = f"{line!r} interpolates a value computed when just runs"
            yield Unknown(origin=Origin(path=path, at=(name, number)), subject=f"the just recipe {name}", reason=reason)
            return
        # `-` before a recipe line: just ignores its failure.
        ignored = "just ignores its failure (-)" if "-" in text[: len(text) - len(text.lstrip("@-"))] else ""
        yield Script(text=text.lstrip("@-"), origin=Origin(path=path, at=(name, number)), advisory=ignored)


def _bound(recipe: Recipe, arguments: list[str]) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for index, (name, default, variadic) in enumerate(recipe.parameters):
        if variadic:
            values[name] = " ".join(arguments[index:]) or default
            break
        values[name] = arguments[index] if index < len(arguments) else default
    return values


def _run(
    justfile: Justfile, path: str, name: str, arguments: list[str], visited: set[str]
) -> Iterator[Script | Unknown]:
    if name in visited:
        return
    visited.add(name)
    recipe = justfile.recipes[name]
    for dependency in recipe.dependencies:
        if dependency in justfile.recipes:
            yield from _run(justfile, path, dependency, [], visited)
    yield from _body(recipe, name, path, {**justfile.variables, **_bound(recipe, arguments)})


def _invocations(justfile: Justfile, words: list[str]) -> Iterator[tuple[str, list[str]]]:
    """Each recipe the words name with its arguments: as many words as it has parameters (all, for a variadic one)."""
    rest = list(words)
    while rest:
        name = rest.pop(0)
        recipe = justfile.recipes.get(name)
        count = 0 if recipe is None else len(recipe.parameters)
        if recipe is not None and any(variadic for _, _, variadic in recipe.parameters):
            count = len(rest)
        yield name, rest[:count]
        rest = rest[count:]


def _justfile(context: Context, command: Command, options: dict[str, str]) -> str | None:
    """The named justfile, or the first found where just runs or in a directory above it, inside the project."""
    directory = posixpath.normpath(
        joined(command.directory, options.get("-d") or options.get("--working-directory") or ".")
    )
    if named := options.get("-f") or options.get("--justfile"):
        return found_at(context, command.directory, [named])
    while True:
        if (found := found_at(context, None if directory == "." else directory, JUSTFILES)) is not None:
            return found
        if directory in ("", "."):
            return None
        directory = posixpath.dirname(directory) or "."


def _words(argv: tuple[str, ...]) -> tuple[list[str], dict[str, str], bool]:
    words: list[str] = []
    options: dict[str, str] = {}
    arguments = iter(argv[1:])
    for word in arguments:
        name, equals, value = word.partition("=")
        if word in _INFORMATION:
            return [], {}, True
        if name in _WITH_VALUES:
            options[name] = value if equals else next(arguments, "")
        elif word == "--set":
            name, value = next(arguments, ""), next(arguments, "")
            words.insert(0, f"{name}={value}")
        elif not word.startswith("-"):
            words.append(word)
    return words, options, False


def _just_recipes(command: Command, context: Context) -> Iterator[Expansion] | None:
    if not command.argv or command.argv[0] != "just":
        return None
    words, options, printing = _words(command.argv)
    if printing or not inside(context, command.directory):
        return None if not printing else iter(())
    if (path := _justfile(context, command, options)) is None:
        return iter((Unknown(origin=command.origin, subject="the justfile", reason="none is found where just runs"),))
    justfile = parse_justfile(context.project.read_text(path))
    while words and _OVERRIDE.fullmatch(words[0]):
        name, _, value = words.pop(0).partition("=")
        justfile.variables[name] = value
    if not words and justfile.recipes:
        words = [next(iter(justfile.recipes))]
    return _expanded(justfile, path, words, command)


def _expanded(justfile: Justfile, path: str, words: list[str], command: Command) -> Iterator[Expansion]:
    visited: set[str] = set()
    for name, arguments in _invocations(justfile, words):
        if name not in justfile.recipes:
            reason = f"{path} does not define it"
            yield Unknown(origin=command.origin, subject=f"the just recipe {name}", reason=reason)
            continue
        yield from _run(justfile, path, name, arguments, visited)


JUST_RECIPES = CommandExpander(name="just recipes", expand=_just_recipes)
