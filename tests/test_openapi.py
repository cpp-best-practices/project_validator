"""The OpenAPI/AsyncAPI profile: two formats recognised by their top-level key, and the linters that validate them."""

from __future__ import annotations

import unittest

from project_validator.checks.schema_validation import schema_validation
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.openapi import API_ECOSYSTEM
from tests.layouts.openapi import ASYNCAPI, OPENAPI
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "OpenAPI description"
RULESET = {".spectral.yaml": "extends: spectral:oas\n"}
VALIDATED = "CI validates the documents against their schemas with {}"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_descriptions_are_told_by_their_top_level_key(self) -> None:
        cases = (
            ({"openapi.yaml": OPENAPI}, {"OpenAPI"}),
            ({"api/shop.json": '{\n  "openapi": "3.0.3",\n  "info": {}\n}\n'}, {"OpenAPI"}),
            ({"swagger.yml": "swagger: '2.0'\ninfo:\n  title: Shop\n"}, {"OpenAPI"}),
            ({"events.yaml": ASYNCAPI}, {"AsyncAPI"}),
            ({"openapi.yaml": OPENAPI, "events.yaml": ASYNCAPI}, {"OpenAPI", "AsyncAPI"}),
        )
        for files, formats in cases:
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, frozenset())
                self.assertEqual(structure.formats & API_ECOSYSTEM.languages, frozenset(formats))
                self.assertEqual(structure.recognised_by["OpenAPI/AsyncAPI"], ("content",))
        # A key that is not at the top level, or a workflow, is no description.
        for files in ({"config.yaml": "tools:\n  openapi: 3.1.0\n"}, {".github/workflows/ci.yml": "on: push\n"}):
            with self.subTest(files=files), temp_project(files) as root:
                self.assertFalse(make_context(root).structure.formats & API_ECOSYSTEM.languages)
        self.assertEqual((API_ECOSYSTEM.kind, API_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in (
            "spectral lint openapi.yaml",
            "redocly lint openapi.yaml",
            "uses: stoplightio/spectral-action@v0.8",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(API_ECOSYSTEM, text))
        self.assertFalse(uses(API_ECOSYSTEM, "npm test"))


class OpenApiTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_linters_validate_and_analyse(self) -> None:
        for files, tool in (
            ({**RULESET, **_ci("spectral lint openapi.yaml")}, "spectral"),
            ({**RULESET, **_ci("npx @stoplight/spectral-cli lint openapi.yaml")}, "spectral"),
            ({**RULESET, **github_action("stoplightio/spectral-action@v0.8", file_glob="openapi.yaml")}, "spectral"),
            (_ci("redocly lint openapi.yaml"), "redocly"),
            (_ci("vacuum lint openapi.yaml"), "vacuum"),
            (_ci("swagger-cli validate openapi.yaml"), "swagger-cli"),
            (_ci("openapi-generator-cli validate -i openapi.yaml"), "openapi-generator"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(schema_validation, files), Result.passed(VALIDATED.format(tool)))
                self.assertEqual(self._run(static_analysis, files).status, Status.PASS)
        # spectral does nothing without a ruleset; the AsyncAPI CLI reads AsyncAPI, not OpenAPI.
        self.assertEqual(self._run(static_analysis, _ci("spectral lint openapi.yaml")).status, Status.WARN)
        self.assertEqual(self._run(schema_validation, _ci("asyncapi validate events.yaml")).status, Status.FAIL)
        self.assertEqual(self._run(schema_validation, _ci("redocly bundle openapi.yaml")).status, Status.FAIL)

    def test_asyncapi_descriptions_are_validated_by_the_asyncapi_cli_or_spectral(self) -> None:
        for files in (
            {"events.yaml": ASYNCAPI, **_ci("asyncapi validate events.yaml")},
            {"events.yaml": ASYNCAPI, **RULESET, **_ci("spectral lint events.yaml")},
        ):
            with self.subTest(files=files), temp_project(files) as root:
                result = schema_validation.run(make_context(root))
                self.assertEqual(result.status, Status.PASS)
        with temp_project({"events.yaml": ASYNCAPI, **_ci("redocly lint events.yaml")}) as root:
            self.assertEqual(schema_validation.run(make_context(root)).status, Status.FAIL)
