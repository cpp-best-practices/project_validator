"""Gathering the files whose text a rule searches for evidence."""

import json
import re
from collections.abc import Iterable

from project_validator.core import Context
from project_validator.text import strip_json_comments


def _at(value: object, keys: tuple[str, ...]) -> object | None:
    """The value at `keys` in nested tables; None when one is missing."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


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
