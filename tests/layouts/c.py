"""Kinds of C project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

C = frozenset({"C"})

# CMake files are deliberately free of project() and settings so that the files a test adds decide what is checked.
LAYOUTS = (
    ProjectLayout(
        name="CMake C",
        files={"CMakeLists.txt": "", "src/main.c": "", "include/app.h": ""},
        languages=C,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="Meson C",
        files={"meson.build": "project('app', 'c')\n", "src/main.c": ""},
        languages=C,
        build_systems=frozenset({"Meson"}),
    ),
)
