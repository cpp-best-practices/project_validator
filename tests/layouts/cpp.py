"""Kinds of C++ project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

CXX = frozenset({"C++"})

# CMake files are deliberately free of project() and settings so that the files a test adds decide what is checked.
LAYOUTS = (
    ProjectLayout(
        name="CMake C++",
        files={"CMakeLists.txt": "", "src/main.cpp": "", "include/app/app.hpp": ""},
        languages=CXX,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="CMake C++ with Python bindings",
        files={"CMakeLists.txt": "", "pyproject.toml": "", "src/module.cpp": "", "python/app/__init__.py": ""},
        languages=CXX | {"Python"},
        build_systems=frozenset({"CMake", "Python packaging"}),
    ),
    ProjectLayout(
        name="Meson C++",
        files={"meson.build": "project('app', 'cpp')\n", "src/main.cpp": ""},
        languages=CXX,
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Header-only C++",
        files={"include/app/app.hpp": ""},
        languages=CXX,
        build_systems=frozenset(),
        # Without a build file there is no build to lay out: nothing to export, guard or keep out of the source tree.
        skipped=frozenset({"out-of-source-build", "compile-commands", "top-level-guard"}),
    ),
)
