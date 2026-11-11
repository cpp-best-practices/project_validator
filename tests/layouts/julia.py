"""Kinds of Julia project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Julia package",
        files={
            "Project.toml": 'name = "Shop"\nuuid = "4a7e2e53-6c0e-4c8a-9c2f-2b6d6b1e5a10"\nversion = "0.1.0"\n',
            "src/Shop.jl": "module Shop\ntotal(prices) = sum(prices)\nend\n",
        },
        languages=frozenset({"Julia"}),
        build_systems=frozenset({"Pkg"}),
    ),
    ProjectLayout(
        name="Julia sources",
        files={"src/shop.jl": "total(prices) = sum(prices)\n"},
        languages=frozenset({"Julia"}),
        build_systems=frozenset(),
    ),
)
