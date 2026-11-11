"""Kinds of Ruby project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Bundler Ruby",
        files={"Gemfile": "", "lib/app.rb": ""},
        languages=frozenset({"Ruby"}),
        build_systems=frozenset({"Bundler"}),
    ),
)
