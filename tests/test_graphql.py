"""The GraphQL profile: a format of schemas and the operations written against them, built and validated by
graphql-inspector or GraphQL Code Generator, linted by graphql-schema-linter or graphql-eslint, formatted by prettier
and diffed for breaking changes by graphql-inspector or rover."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.schema_compatibility import schema_compatibility
from project_validator.checks.schema_validation import schema_validation
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.graphql import GRAPHQL_ECOSYSTEM
from tests.layouts.graphql import OPERATION, SCHEMA
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "GraphQL schema"
VALIDATED = "CI validates the documents against their schemas with {}"
COMPATIBLE = "CI checks the schemas for breaking changes with {}"
VALIDATE = "npx --yes @graphql-inspector/cli validate 'operations/**/*.graphql' schema/schema.graphql"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _formats(files: dict[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    with temp_project(files) as root:
        structure = make_context(root).structure
    return structure.languages, structure.formats


class RecognitionTests(unittest.TestCase):
    def test_a_schema_makes_a_graphql_project_and_its_operations_count(self) -> None:
        for files in (
            {"schema/schema.graphql": SCHEMA, "operations/catalog.graphql": OPERATION},
            {"api/types.graphqls": SCHEMA},
            {"api/shop.gql": "extend type Query {\n  total: Int!\n}\n"},
            {"schema.graphql": "", "queries/catalog.graphql": OPERATION},
            {".graphqlrc.yml": "schema: https://api.example.com/graphql\n", "queries/catalog.graphql": OPERATION},
        ):
            with self.subTest(files=sorted(files)):
                self.assertEqual(_formats(files)[1] - {"YAML"}, frozenset({"GraphQL"}))
        self.assertEqual((GRAPHQL_ECOSYSTEM.kind, GRAPHQL_ECOSYSTEM.toolchain), ("format", None))

    def test_operations_alone_make_nothing(self) -> None:
        # A client's queries, with no schema in the repository and no GraphQL Config naming one.
        with temp_project({"queries/catalog.graphql": OPERATION, "README.md": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.formats, frozenset())
        self.assertIn((".graphql", 1), structure.unrecognised_suffixes)

    def test_a_field_named_type_is_no_definition(self) -> None:
        operation = "query Items {\n  items {\n    type: kind\n    schema\n  }\n}\n"
        self.assertEqual(_formats({"queries/items.graphql": operation})[1], frozenset())

    def test_ci_usage(self) -> None:
        for text in (
            "graphql-inspector diff main:schema.graphql schema.graphql",
            "@graphql-inspector/cli validate 'src/**/*.graphql' schema.graphql",
            "graphql-codegen --config codegen.ts",
            "graphql-schema-linter schema.graphql",
            "rover graph check shop@current --schema schema.graphql",
            "uses: graphql-hive/graphql-inspector@master",
            "uses: kamilkisiela/graphql-inspector@master",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(GRAPHQL_ECOSYSTEM, text))
        self.assertFalse(uses(GRAPHQL_ECOSYSTEM, "npm test"))


class GraphQLTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_operations_are_validated_against_the_schema(self) -> None:
        for line, tool in (
            (VALIDATE, "graphql-inspector"),
            ("graphql-inspector introspect schema/schema.graphql --write schema.json", "graphql-inspector"),
            ("npx graphql-codegen --config codegen.ts", "graphql-codegen"),
            ("npx @graphql-codegen/cli", "graphql-codegen"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(schema_validation, _ci(line)), Result.passed(VALIDATED.format(tool)))
        self.assertEqual(self._run(schema_validation, _ci("graphql-schema-linter schema")).status, Status.FAIL)

    def test_a_diff_fails_on_breaking_changes(self) -> None:
        for line, tool in (
            ("graphql-inspector diff main:schema/schema.graphql schema/schema.graphql", "graphql-inspector"),
            ("rover graph check shop@current --schema schema/schema.graphql", "rover"),
            ("rover subgraph check shop@current --name catalog --schema schema/schema.graphql", "rover"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(schema_compatibility, _ci(line)), Result.passed(COMPATIBLE.format(tool)))
        # A diff builds both schemas, so it validates too; a validation is no diff.
        diff = _ci("graphql-inspector diff main:schema/schema.graphql schema/schema.graphql")
        self.assertEqual(self._run(schema_validation, diff).status, Status.PASS)
        self.assertEqual(self._run(schema_compatibility, _ci(VALIDATE)).status, Status.WARN)
        self.assertEqual(self._run(schema_compatibility, _ci("rover graph publish shop@current")).status, Status.WARN)

    def test_the_inspector_action_diffs_unless_told_not_to_fail(self) -> None:
        action = github_action("graphql-hive/graphql-inspector@master", schema="main:schema/schema.graphql")
        self.assertEqual(self._run(schema_compatibility, action), Result.passed(COMPATIBLE.format("graphql-inspector")))
        self.assertEqual(self._run(schema_validation, action).status, Status.PASS)
        old = github_action("kamilkisiela/graphql-inspector@master", schema="main:schema/schema.graphql")
        self.assertEqual(self._run(schema_compatibility, old).status, Status.PASS)
        annotating = github_action("graphql-hive/graphql-inspector@master", **{"fail-on-breaking": "false"})
        self.assertEqual(self._run(schema_compatibility, annotating).status, Status.WARN)

    def test_the_schema_is_linted(self) -> None:
        self.assertEqual(
            self._run(static_analysis, _ci("graphql-schema-linter 'schema/**/*.graphql'")),
            Result.passed("graphql-schema-linter runs"),
        )
        with_rules = {
            ".graphql-schema-linterrc": '{ "rules": ["types-have-descriptions"] }',
            **_ci("graphql-schema-linter schema"),
        }
        self.assertEqual(
            self._run(static_analysis, with_rules),
            Result.passed("graphql-schema-linter (.graphql-schema-linterrc) runs"),
        )
        self.assertEqual(self._run(static_analysis, _ci("prettier --check .")).status, Status.FAIL)

    def test_eslint_lints_graphql_with_its_plugin(self) -> None:
        # An eslint configuration file is JavaScript, so that project has two ecosystems; a package.json alone is not.
        config = (
            'import graphql from "@graphql-eslint/eslint-plugin";\nexport default [graphql.configs["flat/schema"]];\n'
        )
        with_plugin = {"eslint.config.mjs": config, **_ci("npx eslint .")}
        self.assertIn("GraphQL: graphql-eslint runs", self._run(static_analysis, with_plugin).message)
        package = '{ "devDependencies": { "@graphql-eslint/eslint-plugin": "^4.0.0" } }\n'
        with_dependency = {"package.json": package, **_ci("npx eslint .")}
        self.assertEqual(self._run(static_analysis, with_dependency), Result.passed("graphql-eslint runs"))
        without = {"eslint.config.mjs": "export default [];\n", **_ci("npx eslint .")}
        self.assertIn("GraphQL: no static analyzer runs", self._run(static_analysis, without).message)

    def test_prettier_formats_the_schema(self) -> None:
        self.assertEqual(self._run(code_formatting, _ci("npx prettier --check .")).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("npx prettier --write .")).status, Status.FAIL)
