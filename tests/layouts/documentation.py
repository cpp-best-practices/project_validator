"""Kinds of documentation site, for tests that run a check in every layout: an MkDocs site, an mdBook."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

MKDOCS = "site_name: Shop\nnav:\n  - Home: index.md\n  - Prices: prices.md\n"
PAGES = {"docs/index.md": "# Shop\n\nPrices of the shop.\n", "docs/prices.md": "# Prices\n\nA total is a sum.\n"}
BOOK = '[book]\ntitle = "Shop"\nsrc = "src"\n'

LAYOUTS = (
    ProjectLayout(
        name="MkDocs site",
        files={"mkdocs.yml": MKDOCS, **PAGES},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"MkDocs", "YAML"}),
    ),
    ProjectLayout(
        name="mdBook",
        files={
            "book.toml": BOOK,
            "src/SUMMARY.md": "# Summary\n\n- [Prices](prices.md)\n",
            "src/prices.md": "# Prices\n",
        },
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"mdBook", "TOML"}),
    ),
)
