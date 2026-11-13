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

## `schema-declared`

Every `.proto` file declares its `syntax` (`proto3`; or its `edition`), without which protoc reads it as proto2 with a
warning, and its `package`, without which its messages are in the global namespace (buf's `PACKAGE_DEFINED` rule).

## `schema-compatibility`

`buf breaking` against the main branch (`--against .git#branch=main`) or the registry; `bufbuild/buf-action` runs it
unless `breaking: false`. Warns when CI checks nothing.

## Not judged

`buf.lock` beside a `buf.yaml` with `deps` is a dependency rule (#24). The generated code is the generating language's. The other checks have no tool
for schemas and are skipped.
