"""Gathering the files whose text a rule searches for evidence."""

import tomllib
from collections.abc import Iterable

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
