"""Gathering the files whose text a rule searches for evidence."""

from collections.abc import Iterable

from project_validator.core import Context


def first_existing(context: Context, names: Iterable[str]) -> str | None:
    return next((name for name in names if context.project.exists(name)), None)


def existing_texts(context: Context, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in names if context.project.exists(name))
