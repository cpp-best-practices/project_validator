"""Kinds of Fortran project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

FORTRAN = frozenset({"Fortran"})

LAYOUTS = (
    ProjectLayout(
        name="fpm package",
        files={
            "fpm.toml": 'name = "app"\n',
            "src/app.f90": "module app\nend module app\n",
            "app/main.f90": "program main\nend program\n",
        },
        languages=FORTRAN,
        build_systems=frozenset({"fpm"}),
    ),
    ProjectLayout(
        name="CMake Fortran",
        files={"CMakeLists.txt": "project(app LANGUAGES Fortran)\n", "src/main.f90": "program main\nend program\n"},
        languages=FORTRAN,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="Meson Fortran",
        files={"meson.build": "project('app', 'fortran')\n", "main.f90": "program main\nend program\n"},
        languages=FORTRAN,
        build_systems=frozenset({"Meson"}),
    ),
)
