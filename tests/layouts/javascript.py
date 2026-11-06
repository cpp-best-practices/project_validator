"""Kinds of JavaScript/TypeScript project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="npm JavaScript",
        files={"package.json": '{"main": "index.js"}\n', "index.js": ""},
        languages=frozenset({"JavaScript"}),
        build_systems=frozenset({"npm"}),
    ),
    ProjectLayout(
        name="Deno TypeScript",
        files={"deno.json": "{}\n", "main.ts": ""},
        languages=frozenset({"TypeScript"}),
        build_systems=frozenset({"Deno"}),
    ),
)
