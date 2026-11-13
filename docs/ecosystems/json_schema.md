# JSON Schema

A format, recognised by intent, never by plain `.json` files: a `*.schema.json`, or a JSON file whose top-level
`$schema` names a json-schema.org dialect, makes the project a JSON Schema one. A file whose `$schema` names another
schema (a tool's configuration) is an instance, not a schema. The schemas and the documents are JSON, the Data
format's, so `data-wellformed` already covers one that does not parse.

A CI job works with the ecosystem when it runs check-jsonschema, ajv, the `jsonschema` CLI or jv.

## `schema-validation`

CI validates the documents against their schemas: `check-jsonschema --schemafile <schema> <documents>` (or its
pre-commit hook), `ajv validate -s <schema> -d <documents>` or `ajv test` (ajv-cli), `jsonschema -i <document>
<schema>`, or `jv <schema> <documents>`.

## `code-formatting`

prettier (`--check`, `--list-different`) or biome (`biome format`, `biome ci`, `biome check` without `--write`), with
their configuration where the JavaScript profile reads it (`.prettierrc`, `biome.json`), or their defaults.

## Not judged

Whether each schema names its dialect and `$id` (`schema-declared`), comes with valid and invalid examples CI checks
(`schema-examples`), and is diffed for breaking changes (`schema-compatibility`) are the other schema practices of
#85, not yet built. The language practices (coverage, platform matrix, …) have no tool for a schema and are skipped.
