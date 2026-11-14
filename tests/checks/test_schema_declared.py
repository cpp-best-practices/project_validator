"""The schema-declared check: every schema of each format, in each unit, declares its dialect and identifier; judged
from the `SchemaDeclaration` facts by the declaration question and policy."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.checks.schema_declared import schema_declared
from project_validator.core import Result, Status
from project_validator.facts.declaration import SchemaDeclaration
from project_validator.policy.declaration import judge_schema_declared
from project_validator.questions.declaration import DeclarationAnswer
from project_validator.runner import run_check
from tests.layouts.json_schema import SCHEMA
from tests.layouts.openapi import ASYNCAPI, OPENAPI
from tests.layouts.protobuf import PROTO
from tests.layouts.tabular_data import DATAPACKAGE
from tests.layouts.xml_schemas import CATALOG, XSD
from tests.support import make_context, temp_project

DRAFT_07 = SCHEMA.replace("https://json-schema.org/draft/2020-12/schema", "http://json-schema.org/draft-07/schema#")
DRAFT_04 = '{\n  "$schema": "http://json-schema.org/draft-04/schema#",\n  "id": "https://example.com/s.json"\n}\n'
NO_ID = SCHEMA.replace('  "$id": "https://shop.example.com/catalog.schema.json",\n', "")
BARE_XSD = XSD.replace(' xmlns="urn:example:catalog"\n           targetNamespace="urn:example:catalog"', "")
SWAGGER = "swagger: '2.0'\ninfo:\n  title: Shop\n  version: 0.1.0\npaths: {}\n"
DECLARED = "{} declares its {}"


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return run_check(schema_declared, make_context(root))


class SchemaDeclaredTests(unittest.TestCase):
    def test_applies_to_the_formats_whose_schemas_declare_themselves(self) -> None:
        self.assertEqual(
            schema_declared.languages,
            frozenset({"JSON Schema", "OpenAPI", "AsyncAPI", "XML Schema", "Protobuf", "Data Package"}),
        )

    def test_a_declared_schema_of_each_format_passes(self) -> None:
        for files, message in (
            (
                {"schema/catalog.schema.json": SCHEMA},
                DECLARED.format("1 JSON Schema file", "dialect ($schema) and $id"),
            ),
            ({"openapi.yaml": OPENAPI}, DECLARED.format("1 OpenAPI file", "version (openapi) and info.version")),
            ({"asyncapi.yaml": ASYNCAPI}, DECLARED.format("1 AsyncAPI file", "version (asyncapi) and info.version")),
            ({"schema/catalog.xsd": XSD}, DECLARED.format("1 XML Schema file", "targetNamespace")),
            ({"proto/shop.proto": PROTO}, DECLARED.format("1 Protobuf file", "syntax (or edition) and package")),
            ({"datapackage.json": DATAPACKAGE}, DECLARED.format("1 Data Package file", "profile ($schema) and name")),
        ):
            with self.subTest(files=files):
                self.assertEqual(_run(files), Result.passed(message))

    def test_what_a_schema_leaves_out_fails_and_is_listed(self) -> None:
        for files, problems in (
            ({"schema/catalog.schema.json": NO_ID}, ("schema/catalog.schema.json: no $id",)),
            (
                {"schema/s.json": '{ "$schema": "https://json-schema.org/draft/2020-12/schema" }\n'},
                ("schema/s.json: no $id",),
            ),
            ({"catalog.schema.json": "{}\n"}, ("catalog.schema.json: no $schema", "catalog.schema.json: no $id")),
            ({"openapi.yaml": "openapi: 3.1.0\ninfo:\n  title: Shop\npaths: {}\n"}, ("openapi.yaml: no info.version",)),
            ({"schema/catalog.xsd": BARE_XSD}, ("schema/catalog.xsd: no targetNamespace",)),
            (
                {"proto/shop.proto": "message Total { int32 total = 1; }\n"},
                ("proto/shop.proto: no syntax", "proto/shop.proto: no package"),
            ),
            (
                {"proto/shop.proto": 'edition = "2023";\nmessage Total { int32 total = 1; }\n'},
                ("proto/shop.proto: no package",),
            ),
            ({"datapackage.yaml": "resources: []\n"}, ("datapackage.yaml: no profile", "datapackage.yaml: no name")),
            (
                {"shop/resource.json": '{ "profile": "tabular-data-resource", "path": "a.csv" }\n'},
                ("shop/resource.json: no name",),
            ),
        ):
            with self.subTest(files=files):
                result = _run(files)
                self.assertEqual((result.status, result.details), (Status.FAIL, problems))
                self.assertRegex(result.message, r"^1 \w[\w ]* file does not declare its ")
        result = _run({"a.schema.json": "{}\n", "b.schema.json": "{}\n", "c.schema.json": SCHEMA})
        self.assertEqual(result.message, "2 JSON Schema files do not declare their dialect ($schema) and $id")

    def test_a_document_of_a_schema_names_the_schemas_location(self) -> None:
        schema = {"schema/catalog.xsd": XSD}
        both = "2 XML Schema files declare their targetNamespace or schema location"
        # `xsi:schemaLocation` on the root element, in the schema's namespace.
        self.assertEqual(_run({**schema, "data/catalog.xml": CATALOG}), Result.passed(both))
        # An `xml-model` processing instruction before it.
        model = CATALOG.replace("?>\n<catalog", '?>\n<?xml-model href="../schema/catalog.xsd"?>\n<catalog', 1)
        unnamed = model.split("<?xml-model")[0] + '<catalog xmlns="urn:example:catalog"/>\n'
        self.assertEqual(_run({**schema, "data/catalog.xml": model}), Result.passed(both))
        self.assertEqual(
            _run({**schema, "data/catalog.xml": unnamed}),
            Result.failed(
                "1 XML Schema file does not declare its targetNamespace or schema location",
                "data/catalog.xml: no schema location",
            ),
        )
        # A schema with no namespace describes the documents whose root is one of its global elements.
        without = '<catalog xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" {}/>\n'
        bare = {"schema/catalog.xsd": BARE_XSD}
        located = without.format('xsi:noNamespaceSchemaLocation="../schema/catalog.xsd"')
        result = _run({**bare, "data/catalog.xml": located})
        self.assertEqual((result.status, result.details), (Status.FAIL, ("schema/catalog.xsd: no targetNamespace",)))
        result = _run({**bare, "data/catalog.xml": without.format("")})
        self.assertEqual(
            result.details, ("schema/catalog.xsd: no targetNamespace", "data/catalog.xml: no schema location")
        )

    def test_xml_of_other_schemas_is_not_a_document_of_the_projects(self) -> None:
        # A build file in its own namespace, a settings file of no namespace and another root, files that do not
        # parse (`data-wellformed` says so; a schema among them describes nothing) and a test suite's document,
        # which is reported, not judged.
        files = {
            "schema/catalog.xsd": XSD,
            "schema/broken.xsd": "<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'",
            "empty.xml": "",
            "pom.xml": '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion></project>\n',
            "settings.xml": "<settings><item/></settings>\n",
            "broken.xml": "<catalog xmlns='urn:example:catalog'>\n",
            "tests/data/catalog.xml": '<catalog xmlns="urn:example:catalog"/>\n',
        }
        self.assertEqual(
            _run(files),
            Result.passed(
                DECLARED.format("1 XML Schema file", "targetNamespace or schema location"),
                "test data, not judged: tests/data/catalog.xml: no schema location",
            ),
        )
        # Without a schema that describes them, no document is asked anything.
        self.assertEqual(
            _run({"schema/catalog.xsd": "<not-a-schema/>\n", "data/catalog.xml": CATALOG}),
            Result.passed("no XML Schema file to judge"),
        )

    def test_a_superseded_dialect_warns(self) -> None:
        result = _run({"schema/catalog.schema.json": DRAFT_07})
        self.assertEqual(
            result,
            Result.warned(
                "1 JSON Schema file declares a superseded dialect",
                "schema/catalog.schema.json: draft-07 is older than 2019-09",
            ),
        )
        # draft-04 named a schema with `id`.
        result = _run({"schema/s.json": DRAFT_04})
        self.assertEqual(
            (result.status, result.details), (Status.WARN, ("schema/s.json: draft-04 is older than 2019-09",))
        )
        result = _run({"openapi.yaml": SWAGGER})
        self.assertEqual(
            result,
            Result.warned(
                "1 OpenAPI file declares a superseded version", "openapi.yaml: Swagger 2.0 is superseded by OpenAPI 3.0"
            ),
        )

    def test_what_is_left_out_fails_before_a_superseded_dialect_warns(self) -> None:
        result = _run(
            {
                "schema/catalog.schema.json": DRAFT_07.replace(
                    '  "$id": "https://shop.example.com/catalog.schema.json",\n', ""
                )
            }
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.details,
            ("schema/catalog.schema.json: no $id", "schema/catalog.schema.json: draft-07 is older than 2019-09"),
        )

    def test_a_test_suites_schemas_are_reported_not_judged(self) -> None:
        result = _run({"schema/catalog.schema.json": SCHEMA, "tests/invalid/missing-id.schema.json": "{}\n"})
        self.assertEqual(
            result,
            Result.passed(
                DECLARED.format("1 JSON Schema file", "dialect ($schema) and $id"),
                "test data, not judged: tests/invalid/missing-id.schema.json: no $schema",
                "test data, not judged: tests/invalid/missing-id.schema.json: no $id",
            ),
        )

    def test_a_schema_that_cannot_be_read_declares_nothing_that_is_judged(self) -> None:
        # Malformed, or not an object: `data-wellformed` says so; a Table Schema alone names no profile or name.
        for files in (
            {"schema/catalog.schema.json": "{ not json", "schema/other.schema.json": SCHEMA},
            {"schema/catalog.schema.json": "true\n", "schema/other.schema.json": SCHEMA},
            {"openapi.yaml": "openapi: [\n", "api/shop.yaml": OPENAPI},
            {"openapi.json": '[\n  {\n    "openapi": "3.1.0"\n  }\n]\n', "api/shop.yaml": OPENAPI},
            {"schema/catalog.xsd": "<not-a-schema/>\n", "schema/other.xsd": XSD},
            {"tableschema.json": '{ "fields": [] }\n', "datapackage.json": DATAPACKAGE},
            {"datapackage.yaml": "- a list\n", "shop/datapackage.json": DATAPACKAGE},
        ):
            with self.subTest(files=files):
                result = _run(files)
                self.assertEqual((result.status, result.details), (Status.PASS, ()))
                self.assertRegex(result.message, r"^1 ")
        self.assertEqual(_run({"datapackage.json": "{ not json"}), Result.passed("no Data Package file to judge"))

    def test_a_format_that_declares_nothing_is_skipped(self) -> None:
        result = judge_schema_declared(DeclarationAnswer(language="YAML", possible=False))
        self.assertEqual(result, Result.skipped("no YAML file declares anything"))

    def test_vendored_schemas_are_not_read(self) -> None:
        with temp_project(
            {"vendor/upstream/catalog.schema.json": "{}\n", "schema/catalog.schema.json": SCHEMA}
        ) as root:
            context = make_context(root)
            self.assertEqual(
                [found.path for found in context.facts.of(SchemaDeclaration)], ["schema/catalog.schema.json"]
            )
            self.assertEqual(run_check(schema_declared, context).status, Status.PASS)
        result = _run({"vendor/upstream/catalog.schema.json": "{}\n"})
        self.assertEqual(result, Result.passed("no JSON Schema file to judge"))

    def test_each_format_is_judged_and_the_results_are_labelled(self) -> None:
        result = _run({"schema/catalog.schema.json": NO_ID, "schema/catalog.xsd": XSD})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "JSON Schema: 1 JSON Schema file does not declare its dialect ($schema) and $id; "
            "XML schemas: 1 XML Schema file declares its targetNamespace",
        )

    def test_does_not_apply_without_schemas(self) -> None:
        with temp_project({"src/main.cpp": "", "config.yaml": "a: 1\n"}) as root:
            self.assertEqual(run_check(schema_declared, make_context(root)), Result.skipped("not applicable to C++"))
