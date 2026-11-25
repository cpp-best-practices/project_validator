"""Kinds of Gleam project, for tests that run a check in every layout: a package."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Gleam package",
        files={
            "gleam.toml": 'name = "shop"\nversion = "1.0.0"\n',
            "src/shop.gleam": "pub fn total() -> Int {\n  0\n}\n",
        },
        languages=frozenset({"Gleam"}),
        build_systems=frozenset({"gleam"}),
    ),
)
