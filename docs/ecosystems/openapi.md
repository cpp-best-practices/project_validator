# OpenAPI/AsyncAPI

Two formats recognised by intent: a YAML or JSON file whose top-level key is `openapi` (or `swagger`, the 2.0 name)
is an OpenAPI description, one whose key is `asyncapi` an AsyncAPI description. The files stay YAML or JSON, the
Data format's. A CI job works with the ecosystem when it runs spectral, redocly, vacuum, swagger-cli or the AsyncAPI
CLI, or the `stoplightio/spectral-action` action.

## `schema-validation`

CI lints the description against its specification: spectral (`spectral lint`, with a ruleset in `.spectral.yaml`,
which it does nothing without; or `stoplightio/spectral-action`), redocly (`redocly lint`; `redocly.yaml`), vacuum
(`vacuum lint`), `swagger-cli validate`, `openapi-generator-cli validate`; for AsyncAPI, spectral or `asyncapi
validate`.

## `static-analysis`

The same linters: a lint of an API description is its validation and its analysis at once.

## `schema-declared`

Every description declares its specification version (`openapi`, or `asyncapi`) and its own (`info.version`). A
Swagger 2.0 description (`swagger: "2.0"`) warns: OpenAPI 3.0 superseded it.

## `schema-examples`

The description's examples are checked against their schemas by spectral (`oas3-valid-media-example`,
`oas3-valid-schema-example`, in `spectral:oas`; the AsyncAPI ruleset's example rules), redocly
(`no-invalid-media-type-examples`) or vacuum, or for real by contract tests: `schemathesis run` (or `st run`), dredd.
Warns when CI checks none.

## `schema-compatibility`

CI checks an OpenAPI description for breaking changes against the main branch's: `oasdiff breaking <base> <revision>`
(`oasdiff diff` and `changelog` only report), the `oasdiff/oasdiff-action/breaking` action with its `base` and
`revision`, or `openapi-diff` with `--fail-on-incompatible`. Warns when CI checks nothing. The AsyncAPI CLI's `diff`
reports breaking changes without failing on them, so AsyncAPI is not asked.

## Not judged

The other checks have no tool for a description and are skipped.
