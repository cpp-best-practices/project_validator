"""Kinds of JavaScript project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="npm JavaScript",
        files={"package.json": '{"main": "index.js"}\n', "index.js": ""},
        languages=frozenset({"JavaScript"}),
        build_systems=frozenset({"npm"}),
    ),
)
