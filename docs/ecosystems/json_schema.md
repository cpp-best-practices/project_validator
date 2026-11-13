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

## `schema-declared`

Every schema names its dialect (`$schema`) and itself (`$id`; `id` in draft-04 and before). A dialect older than
2019-09 (draft-07 and before) warns. A schema under a test directory is reported, not judged.

## `schema-examples`

CI checks the examples that come with the schemas: `ajv test -s <schema> -d 'examples/valid/*.json' --valid` (and
`--invalid` on the invalid ones), which asserts what each example is for; or a validator (check-jsonschema, `ajv
validate`, the `jsonschema` CLI, jv) run on an `examples` (or `samples`, `valid`, `invalid`) directory. Warns when
CI checks none.

## Not judged

Whether the schemas are diffed for breaking changes (`schema-compatibility`) is the last schema practice of #85, not
yet built. The language practices (coverage, platform matrix, …) have no tool for a schema and are skipped.
