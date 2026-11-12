"""The schema-validation check: CI validates each format's documents against their schemas, or fails; a project with
nothing to validate is not asked."""

from __future__ import annotations

import unittest

from project_validator.checks.schema_validation import schema_validation
from project_validator.core import Result, Status
from project_validator.facts.schema import SCHEMA
from tests.support import github_job, run_in_layout


class SchemaValidationTests(unittest.TestCase):
    def test_applies_to_the_formats_with_a_validator(self) -> None:
        self.assertEqual(schema_validation.aspect, SCHEMA)
        self.assertLessEqual({"JSON Schema", "Kubernetes"}, schema_validation.languages)

    def test_a_validator_run_passes_and_none_fails(self) -> None:
        validated = github_job(
            "ubuntu-latest", "check-jsonschema --schemafile schema/catalog.schema.json data/catalog.json"
        )
        self.assertEqual(
            run_in_layout(self, "JSON Schema", schema_validation, validated),
            Result.passed("CI validates the documents against their schemas with check-jsonschema"),
        )
        result = run_in_layout(
            self, "JSON Schema", schema_validation, github_job("ubuntu-latest", "prettier --check .")
        )
        self.assertEqual(
            (result.status, result.message), (Status.FAIL, "no schema validation found in CI configuration")
        )
        self.assertTrue(result.details[0].startswith("consider running in CI: "))
        kubernetes = github_job("ubuntu-latest", "helm template charts/shop | kubeconform -strict")
        self.assertEqual(
            run_in_layout(self, "Kubernetes manifests", schema_validation, kubernetes),
            Result.passed("CI validates the documents against their schemas with kubeconform"),
        )

    def test_a_project_with_nothing_to_validate_is_not_asked(self) -> None:
        result = run_in_layout(self, "CMake C++", schema_validation, github_job("ubuntu-latest", "cmake --build build"))
        self.assertEqual(result.status, Status.SKIP)
