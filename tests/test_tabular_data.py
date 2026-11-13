"""The tabular data profile: Data Packages, a format recognised by intent, and the validators of their tables."""

from __future__ import annotations

import unittest

from project_validator.checks.schema_validation import schema_validation
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.tabular_data import TABULAR_DATA_ECOSYSTEM
from tests.layouts.tabular_data import COUNTRIES, DATAPACKAGE
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Data Package"
VALIDATED = "CI validates the documents against their schemas with {}"
NOT_VALIDATED = (Status.FAIL, "no schema validation found in CI configuration")
PROFILE_V1 = '{\n  "profile": "tabular-data-package",\n  "name": "shop",\n  "resources": []\n}\n'
PACKAGE_YAML = "profile: tabular-data-package\nname: shop\nresources: []\n"
TABLE_SCHEMA = '{\n  "fields": [{ "name": "code", "type": "string" }]\n}\n'


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_descriptors_are_told_by_name_or_by_profile_never_by_a_table_alone(self) -> None:
        for files, data_format in (
            ({"datapackage.json": DATAPACKAGE, "data/countries.csv": COUNTRIES}, "JSON"),
            ({"datapackage.yaml": PACKAGE_YAML}, "YAML"),
            ({"schema/tableschema.json": TABLE_SCHEMA}, "JSON"),
            ({"packages/shop.json": PROFILE_V1}, "JSON"),
            ({"shop/package.yaml": "$schema: https://datapackage.org/profiles/2.0/datapackage.json\n"}, "YAML"),
        ):
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(
                    (structure.languages, structure.formats), (frozenset(), frozenset({"Data Package", data_format}))
                )
                self.assertEqual(structure.recognised_by["Tabular data"], ("content",))
        for files in (
            {"data/countries.csv": COUNTRIES},
            {"data/catalog.json": '[{ "name": "apple" }]\n'},
            {"config/tool.json": '{ "$schema": "https://json.schemastore.org/tsconfig", "fields": [] }\n'},
        ):
            with self.subTest(files=files), temp_project(files) as root:
                self.assertNotIn("Tabular data", make_context(root).structure.recognised_by)
        self.assertEqual((TABULAR_DATA_ECOSYSTEM.kind, TABULAR_DATA_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in (
            "frictionless validate datapackage.json",
            "csvlint --schema=schema.json data.csv",
            "uses: frictionlessdata/frictionless-ci@v2",
            "uses: frictionlessdata/repository@v1",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(TABULAR_DATA_ECOSYSTEM, text))
        self.assertFalse(uses(TABULAR_DATA_ECOSYSTEM, "npm test"))


class TabularDataTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_validators_validate_the_tables_against_their_schemas(self) -> None:
        for line, tool in (
            ("frictionless validate datapackage.json", "frictionless"),
            ("pipx run frictionless validate datapackage.json", "frictionless"),
            ("python -m frictionless validate data/countries.csv --schema schema/countries.json", "frictionless"),
            ("goodtables validate datapackage.json", "goodtables"),
            ("csvlint --schema=schema/countries.json data/countries.csv", "csvlint"),
            ("csvlint -s schema/countries.json data/countries.csv", "csvlint"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(schema_validation, _ci(line)), Result.passed(VALIDATED.format(tool)))
        # Describing a package reads it; csvlint without a schema checks the CSV is well formed, against nothing.
        for line in ("frictionless describe datapackage.json", "csvlint data/countries.csv"):
            with self.subTest(line=line):
                result = self._run(schema_validation, _ci(line))
                self.assertEqual((result.status, result.message), NOT_VALIDATED)
                self.assertIn("consider running in CI: frictionless validate datapackage.json", result.details[0])

    def test_the_frictionless_action_validates_what_its_inputs_name(self) -> None:
        for action in ("frictionlessdata/frictionless-ci@v2", "frictionlessdata/repository@v1"):
            with self.subTest(action=action):
                self.assertEqual(
                    self._run(schema_validation, github_action(action)), Result.passed(VALIDATED.format("frictionless"))
                )
        for inputs in ({"inquiry": "inquiry.yaml"}, {"packages": "**/datapackage.json"}, {"tables": "data/*.csv"}):
            with self.subTest(inputs=inputs):
                workflow = github_action("frictionlessdata/frictionless-ci@v2", **inputs)
                self.assertEqual(self._run(schema_validation, workflow).status, Status.PASS)
