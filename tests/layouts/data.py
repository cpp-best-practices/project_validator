"""Kinds of data project, for tests that run a check in every layout: data files and nothing else."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Data files",
        files={"config/settings.yaml": "debug: false\n", "data/items.json": "[]\n"},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"JSON", "YAML"}),
    ),
)
