"""Kinds of JSON Schema project, for tests that run a check in every layout: a schema and the documents it describes."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

SCHEMA = """\
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://shop.example.com/catalog.schema.json",
  "title": "Catalog",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["name", "price"],
    "properties": {
      "name": { "type": "string" },
      "price": { "type": "integer", "minimum": 0 }
    }
  }
}
"""
CATALOG = '[\n  { "name": "apple", "price": 1 },\n  { "name": "pear", "price": 2 }\n]\n'

LAYOUTS = (
    ProjectLayout(
        name="JSON Schema",
        files={"schema/catalog.schema.json": SCHEMA, "data/catalog.json": CATALOG},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"JSON Schema", "JSON"}),
    ),
)
