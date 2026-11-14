"""Kinds of GraphQL project, for tests that run a check in every layout: a schema and the operations written against
it."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

SCHEMA = """\
\"\"\"A price list and its total.\"\"\"
type Query {
  \"\"\"The items of the catalog.\"\"\"
  items: [Item!]!
  \"\"\"The sum of the prices.\"\"\"
  total: Int!
}

\"\"\"An item for sale.\"\"\"
type Item {
  \"\"\"The item's name.\"\"\"
  name: String!
  \"\"\"The price, in cents.\"\"\"
  price: Int!
}
"""
OPERATION = "query Catalog {\n  items {\n    name\n    price\n  }\n  total\n}\n"

LAYOUTS = (
    ProjectLayout(
        name="GraphQL schema",
        files={"schema/schema.graphql": SCHEMA, "operations/catalog.graphql": OPERATION},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"GraphQL"}),
    ),
)
