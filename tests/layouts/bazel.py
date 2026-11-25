"""Kinds of Bazel project, for tests that run a check in every layout: Bazel modules and macros and nothing else."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Bazel modules",
        files={
            "MODULE.bazel": 'module(name = "shop")\n',
            "shop/defs.bzl": 'def shop_prices(name):\n    native.filegroup(name = name, srcs = ["prices.txt"])\n',
        },
        languages=frozenset(),
        build_systems=frozenset({"Bazel"}),
        formats=frozenset({"Bazel"}),
    ),
)
