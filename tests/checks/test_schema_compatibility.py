"""The schema-compatibility check: CI checks each format's schemas for breaking changes, or warns; a format with no
tool that checks them is not asked."""

from __future__ import annotations

import unittest

from project_validator.checks.schema_compatibility import schema_compatibility
from project_validator.core import Result, Status
from project_validator.facts.schema import COMPATIBILITY
from tests.support import github_action, github_job, run_in_layout

CHECKED = "CI checks the schemas for breaking changes with {}"
NOT_CHECKED = (Status.WARN, "no check for breaking schema changes found in CI configuration")


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class SchemaCompatibilityTests(unittest.TestCase):
    def test_applies_to_the_formats_with_a_compatibility_checker(self) -> None:
        self.assertEqual(schema_compatibility.aspect, COMPATIBILITY)
        self.assertEqual(schema_compatibility.languages, frozenset({"JSON Schema", "OpenAPI", "Protobuf"}))

    def test_json_schemas_are_diffed_against_the_base(self) -> None:
        checked = _ci(
            "git fetch --depth=1 origin main && git show origin/main:schema/catalog.schema.json > /tmp/base.json",
            "npx --yes json-schema-diff /tmp/base.json schema/catalog.schema.json",
        )
        result = run_in_layout(self, "JSON Schema", schema_compatibility, checked)
        self.assertEqual(result, Result.passed(CHECKED.format("json-schema-diff")))
        validated = _ci("check-jsonschema --schemafile schema/catalog.schema.json data/catalog.json")
        result = run_in_layout(self, "JSON Schema", schema_compatibility, validated)
        self.assertEqual((result.status, result.message), NOT_CHECKED)
        self.assertIn("consider running in CI: json-schema-diff", result.details[0])

    def test_api_descriptions_are_diffed_by_oasdiff_or_openapi_diff(self) -> None:
        for files, tool in (
            (_ci("oasdiff breaking /tmp/base.yaml openapi.yaml --fail-on ERR"), "oasdiff"),
            (
                github_action(
                    "oasdiff/oasdiff-action/breaking@v0", base="origin/main:openapi.yaml", revision="HEAD:openapi.yaml"
                ),
                "oasdiff",
            ),
            (_ci("openapi-diff /tmp/base.yaml openapi.yaml --fail-on-incompatible"), "openapi-diff"),
        ):
            with self.subTest(files=files):
                result = run_in_layout(self, "OpenAPI description", schema_compatibility, files)
                self.assertEqual(result, Result.passed(CHECKED.format(tool)))
        # `oasdiff diff` and `changelog` report every change without failing; openapi-diff fails only when told to.
        for line in (
            "oasdiff diff /tmp/base.yaml openapi.yaml",
            "oasdiff changelog /tmp/base.yaml openapi.yaml",
            "openapi-diff /tmp/base.yaml openapi.yaml",
            "redocly lint openapi.yaml",
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, "OpenAPI description", schema_compatibility, _ci(line))
                self.assertEqual((result.status, result.message), NOT_CHECKED)

    def test_protobuf_schemas_are_checked_by_buf_breaking(self) -> None:
        for files in (
            _ci("buf breaking --against .git#branch=main"),
            github_action("bufbuild/buf-action@v1"),
        ):
            with self.subTest(files=files):
                result = run_in_layout(self, "Protobuf module", schema_compatibility, files)
                self.assertEqual(result, Result.passed(CHECKED.format("buf breaking")))
        for files in (_ci("buf lint"), github_action("bufbuild/buf-action@v1", breaking="false")):
            with self.subTest(files=files):
                result = run_in_layout(self, "Protobuf module", schema_compatibility, files)
                self.assertEqual((result.status, result.message), NOT_CHECKED)

    def test_a_format_with_no_compatibility_checker_is_not_asked(self) -> None:
        for layout in ("XML Schema", "Data Package", "CMake C++"):
            with self.subTest(layout=layout):
                result = run_in_layout(self, layout, schema_compatibility, _ci("xmllint --noout data/catalog.xml"))
                self.assertEqual(result.status, Status.SKIP)
