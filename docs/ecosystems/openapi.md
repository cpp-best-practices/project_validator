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

## Not judged

The other schema practices of #85 are not yet built: the version declared (`openapi` 3.0 or later, `info.version`),
the examples checked (spectral's `oas3-valid-*-example` rules) or contract-tested (schemathesis, dredd), and breaking
changes (`oasdiff breaking`, openapi-diff). The other checks have no tool for a description and are skipped.
