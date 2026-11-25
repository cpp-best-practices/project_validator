"""Kinds of CMake project, for tests that run a check in every layout: CMake modules and nothing else."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="CMake modules",
        files={
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.25)\nproject(shop LANGUAGES NONE)\n",
            "cmake/Shop.cmake": "function(shop_add_prices target)\nendfunction()\n",
        },
        languages=frozenset(),
        build_systems=frozenset({"CMake"}),
        formats=frozenset({"CMake"}),
    ),
)
