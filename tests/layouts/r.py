"""Kinds of R project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="R package",
        files={
            "DESCRIPTION": "Package: shop\nVersion: 0.1.0\nTitle: Prices of the Shop's Items\nLicense: MIT\n",
            "NAMESPACE": "export(total)\n",
            "R/shop.R": "total <- function(prices) sum(prices)\n",
        },
        languages=frozenset({"R"}),
        build_systems=frozenset({"R package"}),
    ),
    ProjectLayout(
        name="R scripts",
        files={"analysis/shop.R": "total <- function(prices) sum(prices)\n"},
        languages=frozenset({"R"}),
        build_systems=frozenset(),
    ),
)
