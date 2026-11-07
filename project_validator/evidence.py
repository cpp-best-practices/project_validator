"""Gathering the files whose text a rule searches for evidence."""

import json
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping

from project_validator.core import Context
from project_validator.text import strip_json_comments


def first_existing(context: Context, names: Iterable[str]) -> str | None:
    return next((name for name in names if context.project.exists(name)), None)


def existing_texts(context: Context, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in names if context.project.exists(name))


def _at(value: object, keys: tuple[str, ...]) -> object | None:
    """The value at `keys` in nested tables; None when one is missing."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def toml_value(context: Context, path: str, *keys: str) -> object | None:
    """The value at `keys` in the TOML file `path`; None when the file, or the value, is missing or does not parse."""
    if not context.project.exists(path):
        return None
    try:
        value: object = tomllib.loads(context.project.read_text(path))
    except tomllib.TOMLDecodeError:
        return None
    return _at(value, keys)


def json_value(context: Context, path: str, *keys: str, comments: bool = False) -> object | None:
    """The value at `keys` in the JSON file `path` (with `comments`, JSON with comments and trailing commas); None
    when the file, or the value, is missing or does not parse."""
    if not context.project.exists(path):
        return None
    text = context.project.read_text(path)
    try:
        value: object = json.loads(strip_json_comments(text) if comments else text)
    except json.JSONDecodeError:
        return None
    return _at(value, keys)


# pre-commit's configuration: a hook it runs counts as evidence much as a CI step does.
PRE_COMMIT_CONFIGURATION = (".pre-commit-config.yaml", ".pre-commit-config.yml")


def ci_and_hook_texts(context: Context) -> tuple[str, ...]:
    """CI configuration and pre-commit's: a tool that either runs is run."""
    return (*context.ci_texts, *existing_texts(context, PRE_COMMIT_CONFIGURATION))


# Where GitHub, GitLab and other forges look for a project's community documents (SECURITY.md, ...).
DOCUMENT_DIRECTORIES = ("", ".github", "docs")


def documents(context: Context, name: re.Pattern[str], directories: Iterable[str] = DOCUMENT_DIRECTORIES) -> list[str]:
    """The files in `directories` whose whole name matches `name`, in the order of `directories`."""
    found = []
    for directory in directories:
        folder = context.project.root / directory
        if folder.is_dir():
            names = sorted(entry.name for entry in folder.iterdir() if entry.is_file() and name.fullmatch(entry.name))
            found += [f"{directory}/{entry}" if directory else entry for entry in names]
    return found


def _nothing_related(_: str) -> Iterator[str]:
    return iter(())


def scripts_run(
    texts: Iterable[str],
    scripts: Mapping[str, str],
    called: Callable[[str], Iterable[str]],
    related: Callable[[str], Iterable[str]] = _nothing_related,
) -> tuple[str, ...]:
    """The texts of the `scripts` (name -> script) that `texts` run, with the scripts those run in turn.

    `called` names the scripts a text runs (`npm run lint` runs lint); `related` names the scripts that running a
    script runs too (its pre and post scripts). A script that does not exist is not run.
    """
    pending = [name for text in texts for name in called(text)]
    run: dict[str, None] = {}
    while pending:
        name = pending.pop()
        if name in run or name not in scripts:
            continue
        run[name] = None
        pending += [*related(name), *called(scripts[name])]
    return tuple(scripts[name] for name in run)
