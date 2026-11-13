"""prettier: JavaScript's formatter, and of much else it reads (JSON, YAML, Markdown). Each profile whose files it
formats makes it its own for its languages (`prettier_tool`); its configuration (`.prettierrc` and the `prettier` key
of package.json) is the JavaScript profile's to read, and it has a default style."""

from __future__ import annotations

from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.tools import Tool, defined_by


def prettier_tool(languages: frozenset[str]) -> Tool:
    """prettier as the formatter of `languages`: `--check` (or `--list-different`) checks, `--write` applies."""
    return format_tool(
        name="prettier",
        languages=languages,
        can={Enforcement.CHECK: "prettier --check .", Enforcement.APPLY: "prettier --write ."},
        formats=flagged(("prettier",), checks=("--check", "-c", "--list-different", "-l"), applies=("--write", "-w")),
        style=defined_by(files=("prettier",), settings=("prettier",)),
        reads=("prettier", "package.json prettier"),
    )
