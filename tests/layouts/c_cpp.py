"""Kinds of C/C++ project, for tests that run a check in every layout."""

from project_validator.ecosystems import C_FAMILY
from tests.layouts.model import ProjectLayout

# CMake files are deliberately free of project() and settings so that the files a test adds decide what is checked.
LAYOUTS = (
    ProjectLayout(
        name="CMake C++",
        files={"CMakeLists.txt": "", "src/main.cpp": "", "include/app/app.hpp": ""},
        languages=C_FAMILY,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="CMake C",
        files={"CMakeLists.txt": "", "src/main.c": "", "include/app.h": ""},
        languages=C_FAMILY,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="CMake C++ with Python bindings",
        files={"CMakeLists.txt": "", "pyproject.toml": "", "src/module.cpp": "", "python/app/__init__.py": ""},
        languages=C_FAMILY | {"Python"},
        build_systems=frozenset({"CMake", "Python packaging"}),
    ),
    ProjectLayout(
        name="Meson C++",
        files={"meson.build": "project('app', 'cpp')\n", "src/main.cpp": ""},
        languages=frozenset({"C++"}),
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Meson C",
        files={"meson.build": "project('app', 'c')\n", "src/main.c": ""},
        languages=frozenset({"C"}),
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Header-only C++",
        files={"include/app/app.hpp": ""},
        languages=frozenset({"C++"}),
        build_systems=frozenset(),
    ),
)
