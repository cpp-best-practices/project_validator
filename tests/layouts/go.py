"""Kinds of Go project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Go module",
        files={"go.mod": "module example.com/app\n", "main.go": "package main\n"},
        languages=frozenset({"Go"}),
        build_systems=frozenset({"Go modules"}),
    ),
)
