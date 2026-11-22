"""Gitignore matching, by pathspec (git's own rules: wildmatch, `**`, anchoring, directory-only entries); it is
required, but imported here so a missing install is reported cleanly instead of crashing."""

from __future__ import annotations

import importlib
from functools import cache
from types import ModuleType
from typing import Any

MISSING_MESSAGE = (
    "pathspec >= 0.12 is required (python3 -m pip install pathspec, or the distro's python3-pathspec package)"
)


def _import_pathspec() -> ModuleType | None:
    try:
        return importlib.import_module("pathspec")
    except ImportError:
        return None


_pathspec = _import_pathspec()


def available() -> bool:
    return _pathspec is not None


@cache
def _spec(glob: str) -> Any:
    if _pathspec is None:
        raise RuntimeError(MISSING_MESSAGE)
    return _pathspec.GitIgnoreSpec.from_lines([glob])


def ignores(glob: str, path: str) -> bool:
    """Whether the gitignore entry `glob`, in an ignore file at the top, ignores `path` (a directory when it ends in
    "/"), or a directory it is in."""
    return bool(_spec(glob).match_file(path))
