"""Kinds of Rust project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Cargo Rust",
        files={"Cargo.toml": "", "src/main.rs": ""},
        languages=frozenset({"Rust"}),
        build_systems=frozenset({"Cargo"}),
    ),
    ProjectLayout(
        name="Meson Rust",
        files={"meson.build": "project('app', 'rust')\n", "src/main.rs": ""},
        languages=frozenset({"Rust"}),
        build_systems=frozenset({"Meson"}),
    ),
)
