"""Gathering the files whose text a rule searches for evidence."""

import re
import tomllib
from collections.abc import Callable, Iterable, Mapping

from project_validator.core import Context


def first_existing(context: Context, names: Iterable[str]) -> str | None:
    return next((name for name in names if context.project.exists(name)), None)


def existing_texts(context: Context, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in names if context.project.exists(name))


def toml_value(context: Context, path: str, *keys: str) -> object | None:
    """The value at `keys` in the TOML file `path`; None when the file, or the value, is missing or does not parse."""
    if not context.project.exists(path):
        return None
    try:
        value: object = tomllib.loads(context.project.read_text(path))
    except tomllib.TOMLDecodeError:
        return None
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


# pre-commit's configuration: a hook it runs counts as evidence much as a CI step does.
PRE_COMMIT_CONFIGURATION = (".pre-commit-config.yaml", ".pre-commit-config.yml")


def ci_and_hook_texts(context: Context) -> tuple[str, ...]:
    """CI configuration and pre-commit's: a tool that either runs is run."""
    return (*context.ci_texts, *existing_texts(context, PRE_COMMIT_CONFIGURATION))


def configuration(
    files: Iterable[str] = (), sections: Mapping[str, re.Pattern[str]] | None = None
) -> Callable[[Context], str | None]:
    """The file that configures a tool: the first of its own `files`, else the first shared file whose text has
    the tool's section (file -> section)."""
    own = tuple(files)
    shared = dict(sections or {})

    def configured(context: Context) -> str | None:
        found = first_existing(context, own)
        if found is not None:
            return found
        present = (path for path in shared if context.project.exists(path))
        return next((path for path in present if shared[path].search(context.project.read_text(path))), None)

    return configured


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
