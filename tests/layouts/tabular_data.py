"""Kinds of tabular data project, for tests that run a check in every layout: a Data Package and its table."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

DATAPACKAGE = """\
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "name": "countries",
  "resources": [
    {
      "name": "countries",
      "path": "data/countries.csv",
      "format": "csv",
      "schema": {
        "fields": [
          { "name": "code", "type": "string", "constraints": { "required": true, "pattern": "[A-Z]{2}" } },
          { "name": "name", "type": "string", "constraints": { "required": true } },
          { "name": "population", "type": "integer", "constraints": { "minimum": 0 } }
        ],
        "primaryKey": ["code"]
      }
    }
  ]
}
"""
COUNTRIES = "code,name,population\nFR,France,68000000\nIS,Iceland,380000\n"

LAYOUTS = (
    ProjectLayout(
        name="Data Package",
        files={"datapackage.json": DATAPACKAGE, "data/countries.csv": COUNTRIES},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Data Package", "JSON"}),
    ),
)
