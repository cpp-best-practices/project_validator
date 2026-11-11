"""Kinds of Python project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Python pyproject",
        files={"pyproject.toml": "", "src/app/__init__.py": ""},
        languages=frozenset({"Python"}),
        build_systems=frozenset({"Python packaging"}),
    ),
    ProjectLayout(
        name="Python setup.py",
        files={"setup.py": "", "app/__init__.py": ""},
        languages=frozenset({"Python"}),
        build_systems=frozenset({"Python packaging"}),
    ),
)
