"""JavaScript and TypeScript are separate ecosystems: they share the npm and Deno tooling, but type checking is
TypeScript's defining gate and not a norm of JavaScript."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.type_checking import type_checking
from project_validator.ecosystems import applies_to
from tests.support import make_context, temp_project

PACKAGE = '{"name": "app", "main": "dist/index.js", "types": "dist/index.d.ts"}\n'


def _structure(files: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """The project's languages, and the language ecosystems recognised (package.json is JSON data too)."""
    with temp_project(files) as root:
        structure = make_context(root).structure
        return sorted(structure.languages), sorted(label for label in structure.recognised_by if label != "Data")


class EcosystemTests(unittest.TestCase):
    def test_javascript_sources_make_a_javascript_project(self) -> None:
        self.assertEqual(
            _structure({"package.json": '{"main": "index.js"}\n', "index.js": ""}), (["JavaScript"], ["JavaScript"])
        )

    def test_typescript_sources_make_a_typescript_project(self) -> None:
        self.assertEqual(_structure({"package.json": PACKAGE, "src/index.ts": ""}), (["TypeScript"], ["TypeScript"]))

    def test_a_package_built_from_typescript_is_not_javascript(self) -> None:
        """Its package.json names the JavaScript it publishes (`main`), but the code is TypeScript."""
        languages, _ = _structure({"package.json": PACKAGE, "src/index.ts": "", "tsconfig.json": "{}\n"})
        self.assertEqual(languages, ["TypeScript"])

    def test_tool_configuration_in_javascript_does_not_make_a_typescript_project_javascript(self) -> None:
        files = {
            "package.json": PACKAGE,
            "src/index.ts": "",
            "eslint.config.js": "",
            "vite.config.mjs": "",
            ".prettierrc.cjs": "",
            "jest.config.js": "",
        }
        self.assertEqual(_structure(files), (["TypeScript"], ["TypeScript"]))

    def test_tool_configuration_of_a_javascript_project_is_javascript(self) -> None:
        self.assertEqual(
            _structure({"package.json": "{}\n", "eslint.config.js": "", "index.js": ""})[0], ["JavaScript"]
        )

    def test_both_languages_make_both(self) -> None:
        self.assertEqual(_structure({"src/index.ts": "", "scripts/build.js": ""})[1], ["JavaScript", "TypeScript"])


class TypeCheckingTests(unittest.TestCase):
    def test_type_checking_is_asked_of_typescript(self) -> None:
        self.assertIn("TypeScript", applies_to(type_checking))

    def test_type_checking_is_not_asked_of_javascript(self) -> None:
        """Type checking JavaScript (checkJs, JSDoc types) is a choice, not the ecosystem's norm."""
        self.assertNotIn("JavaScript", applies_to(type_checking))


if __name__ == "__main__":
    unittest.main()
