# GraphQL

A format, recognised by intent: a schema in the schema definition language makes the project a GraphQL one. A
`.graphqls` file, a `schema.graphql`, a `.graphql` or `.gql` file holding type definitions (`type`, `interface`,
`enum`, `input`, `scalar`, `union`, `schema`, `directive`, or an `extend` of one), or a GraphQL Config file
(`.graphqlrc`, `graphql.config.*`) naming the schema. Once recognised, the `.graphql` and `.gql` files of operations
(queries, mutations, fragments) are the format's too; a client's operations alone, with no schema in the repository,
make nothing, and `--map` lists their suffix as unrecognised.

A CI job works with the ecosystem when it runs graphql-inspector (as `graphql-inspector` or `@graphql-inspector/cli`),
GraphQL Code Generator (`graphql-codegen`, `@graphql-codegen/cli`, `gql-gen`), graphql-schema-linter, Apollo's rover,
or the `graphql-hive/graphql-inspector` action (once `kamilkisiela/graphql-inspector`).

## `schema-validation`

CI builds the schema and validates the operations against it: `graphql-inspector validate <operations> <schema>`,
which fails on an operation the schema does not answer; `graphql-inspector introspect` or `diff`, which build the
schema and fail on an invalid one; or GraphQL Code Generator, which fails on an invalid document.

## `static-analysis`

graphql-schema-linter, with every rule on by default and the project's in `.graphql-schema-linterrc`; or eslint with
`@graphql-eslint/eslint-plugin`, named in the eslint configuration or in `package.json`.

## `code-formatting`

prettier (`--check`, `--list-different`), with its configuration where the JavaScript profile reads it (`.prettierrc`,
`package.json`), or its default style.

## `schema-compatibility`

`graphql-inspector diff <main branch's schema> <schema>`, which fails on a breaking change; the
`graphql-hive/graphql-inspector` action, which diffs a pull request's schema against the ref its `schema` input names
(`main:schema.graphql`) and fails on a breaking change unless `fail-on-breaking` is false, when it only annotates; or
`rover graph check` (`rover subgraph check`), which checks the schema against the graph Apollo Studio holds. Warns when
CI checks nothing.

## Not judged

A GraphQL schema names no dialect or identifier, so `schema-declared` does not ask; no tool checks examples that come
with a schema, so `schema-examples` does not either. `graphql-inspector coverage` and `similar` report without failing.
The generated code is the generating language's. The other checks have no tool for schemas and are skipped.
