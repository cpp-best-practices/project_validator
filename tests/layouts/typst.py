"""Kinds of Typst project, for tests that run a check in every layout: a document."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

DOCUMENT = """\
#set page(paper: "a4")
#let total(prices) = prices.sum()

= Prices of the shop

A total is the sum of the prices: #total((1, 2, 3)).
"""

LAYOUTS = (
    ProjectLayout(
        name="Typst document",
        files={"main.typ": DOCUMENT},
        languages=frozenset({"Typst"}),
        build_systems=frozenset(),
    ),
)
