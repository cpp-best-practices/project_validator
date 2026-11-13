"""The schema-examples check: CI checks the examples that come with each format's schemas, or warns; a format with no
tool that checks examples is not asked."""

from __future__ import annotations

import unittest

from project_validator.checks.schema_examples import schema_examples
from project_validator.core import Result, Status
from project_validator.facts.schema import EXAMPLES
from tests.layouts.openapi import ASYNCAPI
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project

RULESET = {".spectral.yaml": "extends: spectral:oas\n"}
CHECKED = "CI checks the schemas' examples with {}"
NOT_CHECKED = (Status.WARN, "no check of the schemas' examples found in CI configuration")


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class SchemaExamplesTests(unittest.TestCase):
    def test_applies_to_the_formats_with_an_example_checker(self) -> None:
        self.assertEqual(schema_examples.aspect, EXAMPLES)
        self.assertEqual(schema_examples.languages, frozenset({"JSON Schema", "OpenAPI", "AsyncAPI", "XML Schema"}))

    def test_json_schema_examples_are_checked_by_ajv_test_or_a_validator_run_on_them(self) -> None:
        for line, tool in (
            ('npx --yes ajv-cli test -s schema/catalog.schema.json -d "examples/valid/*.json" --valid', "ajv"),
            ("ajv test -s schema/catalog.schema.json -d test/invalid_data.json --invalid", "ajv"),
            ("ajv validate -s schema/catalog.schema.json -d examples/catalog.json", "ajv"),
            ("check-jsonschema --schemafile schema/catalog.schema.json examples/valid/*.json", "check-jsonschema"),
            ("check-jsonschema --schemafile schema/catalog.schema.json samples/catalog.json", "check-jsonschema"),
            ("jsonschema -i examples/valid/catalog.json schema/catalog.schema.json", "jsonschema"),
            ("jv schema/catalog.schema.json Examples/catalog.json", "jv"),
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "JSON Schema", schema_examples, _ci(line))
                self.assertEqual(result, Result.passed(CHECKED.format(tool)))
        # Validating the data is not checking the examples; a path merely containing the word is not an examples
        # directory.
        for line in (
            "check-jsonschema --schemafile schema/catalog.schema.json data/catalog.json",
            "jv schema/catalog.schema.json data/example-catalog.json",
            "ajv compile -s schema/catalog.schema.json",
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "JSON Schema", schema_examples, _ci(line))
                self.assertEqual((result.status, result.message), NOT_CHECKED)
                self.assertIn("ajv test -s <schema>", result.details[0])

    def test_api_description_examples_are_checked_by_the_linters_rules_or_contract_tests(self) -> None:
        for files, tool in (
            ({**RULESET, **_ci("spectral lint openapi.yaml")}, "spectral"),
            ({**RULESET, **github_action("stoplightio/spectral-action@v0.8", file_glob="openapi.yaml")}, "spectral"),
            (_ci("redocly lint openapi.yaml"), "redocly"),
            (_ci("vacuum lint openapi.yaml"), "vacuum"),
            (_ci("schemathesis run openapi.yaml --url http://localhost:8080"), "schemathesis"),
            (_ci("st run openapi.yaml --url http://localhost:8080"), "schemathesis"),
            (_ci("dredd openapi.yaml http://localhost:8080"), "dredd"),
        ):
            with self.subTest(files=files):
                result = run_in_layout(self, "OpenAPI description", schema_examples, files)
                self.assertEqual(result, Result.passed(CHECKED.format(tool)))
        # swagger-cli validates the description's structure, not its examples.
        result = run_in_layout(self, "OpenAPI description", schema_examples, _ci("swagger-cli validate openapi.yaml"))
        self.assertEqual((result.status, result.message), NOT_CHECKED)
        with temp_project({"events.yaml": ASYNCAPI, **RULESET, **_ci("spectral lint events.yaml")}) as root:
            self.assertEqual(schema_examples.run(make_context(root)), Result.passed(CHECKED.format("spectral")))
        with temp_project({"events.yaml": ASYNCAPI, **_ci("asyncapi validate events.yaml")}) as root:
            self.assertEqual(schema_examples.run(make_context(root)).status, Status.WARN)

    def test_xml_schema_examples_are_checked_by_a_validator_run_on_them(self) -> None:
        for line, tool in (
            ("xmllint --noout --schema schema/catalog.xsd examples/valid/*.xml", "xmllint"),
            ("xmllint --relaxng schema/catalog.rng examples/invalid/bad.xml", "xmllint"),
            ("jing schema/catalog.rng examples/*.xml", "jing"),
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "XML Schema", schema_examples, _ci(line))
                self.assertEqual(result, Result.passed(CHECKED.format(tool)))
        for line in (
            "xmllint --noout --schema schema/catalog.xsd data/catalog.xml",
            "xmllint --noout examples/valid/catalog.xml",
            "jing schema/catalog.rng data/catalog.xml",
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "XML Schema", schema_examples, _ci(line))
                self.assertEqual((result.status, result.message), NOT_CHECKED)

    def test_a_format_with_no_example_checker_is_not_asked(self) -> None:
        for layout in ("Protobuf module", "Data Package", "CMake C++"):
            with self.subTest(layout=layout):
                result = run_in_layout(self, layout, schema_examples, _ci("buf build"))
                self.assertEqual(result.status, Status.SKIP)
