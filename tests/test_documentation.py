"""The README documents every check and what it applies to, as the ecosystem registry says."""

import re
import unittest
from pathlib import Path

from project_validator.ecosystems import applies_to, isolated_registry, registered
from project_validator.plugins import discover
from tests.support import temp_project

README = Path(__file__).parent.parent / "README.md"
CHECK_ROW = re.compile(r"^\| `(?P<check>[a-z0-9-]+)` \| (?P<applies_to>[^|]+) \|", re.MULTILINE)


def _checks_section() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("\n## Checks\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end >= 0 else None]


def documented() -> dict[str, str]:
    return {row["check"]: row["applies_to"].strip() for row in CHECK_ROW.finditer(_checks_section())}


class ReadmeTests(unittest.TestCase):
    def test_every_check_is_documented_once(self) -> None:
        rows = [row["check"] for row in CHECK_ROW.finditer(_checks_section())]
        self.assertEqual(sorted(rows), sorted(found.name for found in discover().checks))

    def test_the_applies_to_column_matches_the_registry(self) -> None:
        rows = documented()
        for found in discover().checks:
            with self.subTest(check=found.name):
                self.assertEqual(rows[found.name], ", ".join(applies_to(found)) or "all")


class ReadmeExampleTests(unittest.TestCase):
    def test_the_ecosystem_plugin_example_works(self) -> None:
        text = README.read_text(encoding="utf-8")
        section = text[text.index("### Adding an ecosystem") :]
        start = section.index("```python\n") + len("```python\n")
        example = section[start : section.index("\n```", start)]
        with isolated_registry(), temp_project({"zig.py": example}) as directory:
            plugins = discover([directory])
            self.assertEqual(registered()[-1].label, "Zig")
            formatting = next(found for found in plugins.checks if found.name == "code-formatting")
            self.assertIn("Zig", applies_to(formatting))
