# Protobuf

A format, recognised by `.proto` sources: the schemas, and the gRPC services they define. `buf.yaml` is YAML, the Data
format's, and holds buf's settings. A CI job works with the ecosystem when it runs `buf`, `protoc` (or
`python -m grpc_tools.protoc`), or the `bufbuild/buf-action` and `bufbuild/buf-setup-action` actions.

## `schema-validation`

The schemas compile: `buf build` (or `bufbuild/buf-action`, which builds first), or `protoc` on the files.

## `static-analysis`

`buf lint`, with the STANDARD rules by default and the project's in `buf.yaml`'s `lint` section.

## `code-formatting`

`buf format --diff --exit-code`, which fails on a file it would change (`--diff` alone only prints the change);
`buf format -w` rewrites the files. `bufbuild/buf-action` formats unless `format: false`.

## Not judged

Breaking changes (`buf breaking` against the main branch or the registry; `bufbuild/buf-action` checks them unless
`breaking: false`) are the schema compatibility practice of #85, not yet built. `buf.lock` beside a `buf.yaml` with
`deps` is a dependency rule (#24). The generated code is the generating language's. The other checks have no tool
for schemas and are skipped.
