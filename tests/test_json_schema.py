"""The JSON Schema profile: a format recognised by intent, its validators and formatters."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.schema_validation import schema_validation
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.json_schema import JSON_SCHEMA_ECOSYSTEM
from tests.layouts.json_schema import CATALOG, SCHEMA
from tests.support import github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "JSON Schema"
DIALECT_ONLY = '{\n  "$schema": "https://json-schema.org/draft/2020-12/schema",\n  "type": "object"\n}\n'
INSTANCE_OF_ANOTHER = '{\n  "$schema": "https://json.schemastore.org/tsconfig",\n  "compilerOptions": {}\n}\n'


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_schemas_are_told_by_name_or_by_dialect_never_by_plain_json(self) -> None:
        for files in ({"schema/catalog.schema.json": SCHEMA}, {"schemas/shop.json": DIALECT_ONLY}):
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(
                    (structure.languages, structure.formats), (frozenset(), frozenset({"JSON", "JSON Schema"}))
                )
                self.assertEqual(structure.recognised_by["JSON Schema"], ("content",))
        for files in ({"data/catalog.json": CATALOG}, {"tsconfig.json": INSTANCE_OF_ANOTHER}):
            with self.subTest(files=files), temp_project(files) as root:
                self.assertEqual(make_context(root).structure.formats, frozenset({"JSON"}))
        self.assertEqual((JSON_SCHEMA_ECOSYSTEM.kind, JSON_SCHEMA_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in (
            "check-jsonschema --schemafile s.json d.json",
            "ajv validate -s s.json -d d.json",
            "jv s.json d.json",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(JSON_SCHEMA_ECOSYSTEM, text))
        self.assertFalse(uses(JSON_SCHEMA_ECOSYSTEM, "npm test"))


class JsonSchemaTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_validators_validate_the_documents(self) -> None:
        for line, tool in (
            ("check-jsonschema --schemafile schema/catalog.schema.json data/catalog.json", "check-jsonschema"),
            ("pipx run check-jsonschema --schemafile schema/catalog.schema.json data/*.json", "check-jsonschema"),
            ("npx ajv-cli validate -s schema/catalog.schema.json -d data/catalog.json", "ajv"),
            ("ajv test -s schema/catalog.schema.json -d data/catalog.json --valid", "ajv"),
            ("jsonschema -i data/catalog.json schema/catalog.schema.json", "jsonschema"),
            ("jv schema/catalog.schema.json data/catalog.json", "jv"),
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run(schema_validation, _ci(line)),
                    Result.passed(f"CI validates the documents against their schemas with {tool}"),
                )
        # Compiling a schema checks the schema, not the documents.
        result = self._run(schema_validation, _ci("ajv compile -s schema/catalog.schema.json"))
        self.assertEqual(
            (result.status, result.message), (Status.FAIL, "no schema validation found in CI configuration")
        )
        self.assertIn("consider running in CI:", result.details[0])

    def test_prettier_and_biome_format_the_schemas(self) -> None:
        for line in ("prettier --check .", "npx prettier -l schema", "biome format .", "biome ci .", "biome check ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.PASS)
        configured = {".prettierrc": '{ "printWidth": 100 }\n', **_ci("prettier --check .")}
        self.assertEqual(self._run(code_formatting, configured).message, ".prettierrc is defined and CI runs prettier")
        for line in ("prettier --write .", "biome format --write .", "biome check --fix ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)
