"""tox: the commands `tox -e <envs>` runs, from tox.ini, tox.toml or `[tool.tox]` in pyproject.toml.

An environment runs the commands of its own section (`[testenv:lint]`), or of `[testenv]`, whose lines may be
conditional on the environment's factors (`mypy: mypy src` runs in `3.12-mypy`). Section names and env lists expand
braces (`3.1{0-3}-tests`, `typing-{pyright,ty}`). A factor tox would take from a variable CI sets (`$PYTHON-mypy`) is
not known; the others still choose the lines. `tox` with no `-e` runs its `env_list`.
"""

import configparser
import re
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown, resolved
from project_validator.facts.arguments import positional, program
from project_validator.facts.expansion import CommandExpander, Expansion, Script, found_at

_FILES = ("tox.ini", "tox.toml", "pyproject.toml")
_RUNS = frozenset({"run", "r", "run-parallel", "p", "exec", "e"})
_OPTIONS = frozenset(
    {
        "-e",
        "--env",
        "-f",
        "--factors",
        "-c",
        "--conf",
        "-m",
        "--labels",
        "--root",
        "--workdir",
        "-x",
        "--override",
        "--installpkg",
    }
)
_RANGE = re.compile(r"^(\d+)-(\d+)$")
_BRACES = re.compile(r"\{([^{}]*)\}")
# A tox substitution with a default (`{posargs:-n auto}`) becomes its default; others (`{toxinidir}`) become ".".
_SUBSTITUTION = re.compile(r"\{(\w+)(?::([^{}]*))?\}")


def braces(text: str) -> list[str]:
    """`text` with each brace group expanded: `{a,b}` into alternatives, `{0-3}` into a range of numbers."""
    match = _BRACES.search(text)
    if match is None:
        return [text]
    alternatives: list[str] = []
    for part in match[1].split(","):
        found = _RANGE.match(part.strip())
        alternatives += [str(n) for n in range(int(found[1]), int(found[2]) + 1)] if found else [part.strip()]
    return [
        result
        for alternative in alternatives
        for result in braces(text[: match.start()] + alternative + text[match.end() :])
    ]


def _names(value: object) -> list[str]:
    """Environment names from an env list: comma or newline separated, braces expanded, comments left out."""
    text = "\n".join(map(str, value)) if isinstance(value, list) else str(value or "")
    entries = (entry.split("#", 1)[0].strip() for line in text.splitlines() for entry in _top_level_split(line))
    return [name for entry in entries if entry for name in braces(entry)]


def _top_level_split(line: str) -> list[str]:
    """`line` split at the commas outside braces."""
    parts, depth, current = [], 0, ""
    for character in line:
        depth += {"{": 1, "}": -1}.get(character, 0)
        if character == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += character
    return [*parts, current]


def _holds(condition: str, factors: set[str]) -> bool:
    """Whether a factor condition holds: alternatives separated by commas, each all of its `-`-joined factors, `!`
    negating one. A factor tox takes from a variable is unknown, and does not decide."""
    for alternative in (option for part in _top_level_split(condition) for option in braces(part.strip())):
        wanted = [factor for factor in alternative.split("-") if factor]
        if all((factor[1:] not in factors) if factor.startswith("!") else factor in factors for factor in wanted):
            return True
    return False


def _commands(lines: str, factors: set[str]) -> Iterator[str]:
    """The command lines of an INI `commands` value that run in an environment with `factors`."""
    for raw in lines.replace("\\\n", " ").splitlines():
        line = raw.strip()
        condition, colon, rest = line.partition(":")
        if colon and rest.startswith(" ") and re.fullmatch(r"[\w.,!{}\- ]+", condition):
            if _holds(condition.strip(), factors):
                yield rest.strip()
        elif line:
            yield line


def _ini(text: str) -> configparser.ConfigParser | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    return parser


def _pattern(name: str) -> re.Pattern[str]:
    """An environment name as a pattern: a part tox takes from a variable (`$PYTHON-tests`) matches any."""
    return re.compile(
        "".join(".+" if part.startswith("$") else re.escape(part) for part in re.split(r"(\$\{?\w+\}?)", name))
    )


def _ini_envs(parser: configparser.ConfigParser, name: str) -> list[tuple[str, str]]:
    """The sections that define the commands of the environment `name` (each one its name may be), with those
    commands; `[testenv]` when none does."""
    wanted = _pattern(name)
    own = [
        (section, parser.get(section, "commands"))
        for section in parser.sections()
        if section.startswith("testenv:")
        and parser.has_option(section, "commands")
        and any(wanted.fullmatch(found) for found in braces(section.removeprefix("testenv:")))
    ]
    if own or not (parser.has_section("testenv") and parser.has_option("testenv", "commands")):
        return own
    return [("testenv", parser.get("testenv", "commands"))]


def _toml_tables(path: str, text: str) -> Mapping[str, object] | None:
    try:
        document: object = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    if PurePosixPath(path).name == "pyproject.toml":
        document = document.get("tool", {}).get("tox") if isinstance(document, Mapping) else None
    return document if isinstance(document, Mapping) and document else None


def _toml_env(tables: Mapping[str, object], name: str) -> tuple[str, list[str]] | None:
    """The table that defines environment `name`'s commands (each a list of arguments), and those commands."""
    envs = tables.get("env")
    own = envs.get(name) if isinstance(envs, Mapping) else None
    for key, table in ((f"env.{name}", own), ("env_run_base", tables.get("env_run_base"))):
        commands = table.get("commands") if isinstance(table, Mapping) else None
        if isinstance(commands, list):
            return key, [" ".join(map(str, command)) for command in commands if isinstance(command, list)]
    return None


def _substituted(line: str) -> str:
    return _SUBSTITUTION.sub(lambda match: match[2] if match[2] is not None else ".", line)


def _env_commands(
    found: configparser.ConfigParser | None, tables: Mapping[str, object] | None, name: str
) -> list[tuple[str, list[str]]]:
    """The command lines environment `name` runs, by the section or table that defines them."""
    if found is not None:
        return [(section, list(_commands(lines, set(name.split("-"))))) for section, lines in _ini_envs(found, name)]
    defined = _toml_env(tables, name) if tables is not None else None
    return [] if defined is None else [defined]


def _env_list(found: configparser.ConfigParser | None, tables: Mapping[str, object] | None) -> list[str]:
    if found is not None:
        return _names(found.get("tox", "env_list", fallback=found.get("tox", "envlist", fallback="")))
    return _names(tables.get("env_list") if tables is not None else None)


def _env_scripts(path: str, text: str, names: list[str] | None, factors: list[str]) -> Iterator[Expansion]:
    """The commands of the environments `names` (by default, the env list; with `factors`, those of its environments
    that have them all)."""
    directory = str(PurePosixPath(path).parent)
    found = _ini(text) if path.endswith(".ini") else None
    tables = None if found is not None else _toml_tables(path, text)
    if found is None and tables is None:
        yield Unknown(origin=Origin(path=path), subject="the tox environments", reason=f"{path} does not parse")
        return
    if names is None:
        names = [name for name in _env_list(found, tables) if set(factors) <= set(name.split("-"))]
    for name in dict.fromkeys(names):
        for section, lines in _env_commands(found, tables, name):
            origin = Origin(path=path, at=(section, "commands"))
            yield from (Script(text=_substituted(line), origin=origin, directory=directory) for line in lines)


def _tox(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`tox -e lint`, `tox run -e 3.12-mypy`, `tox p`, or `tox` (its env_list): the commands each environment runs."""
    argv = resolved(command)
    if program(argv) != "tox":
        return None
    words, options = positional(argv, _OPTIONS)
    if words and words[0] not in _RUNS:
        return iter(())  # another subcommand (`tox list`, `tox config`) runs no environment
    envs = options.get("-e") or options.get("--env")
    named = options.get("-c") or options.get("--conf")
    path = found_at(context, command.directory, [named] if named else _FILES)
    if path is None or (
        not named and path.endswith("pyproject.toml") and "[tool.tox" not in context.project.read_text(path)
    ):
        return iter(
            (Unknown(origin=command.origin, subject="the tox environments", reason="no tox configuration is found"),)
        )
    factors = [
        factor for value in (options.get("-f"), options.get("--factors")) if value for factor in value.split(",")
    ]
    return _env_scripts(path, context.project.read_text(path), _names(envs) if envs else None, factors)


TOX = CommandExpander(name="tox environments", expand=_tox)
