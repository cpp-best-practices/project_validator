# Go

Recognised by `.go` sources and Go modules (`go.mod`).

## `tests-run`

`Test` functions in `*_test.go` files run by `go test`.

## `coverage`

Go's tools measure statements only, so Go needs statement coverage: `go test -cover` or `-coverprofile`.

## `platform-matrix`

The toolchains are Go versions.

## `compiler-warnings`

`go vet` and staticcheck (golangci-lint runs both).

## `hardening`

Programs are built as position-independent executables (`-buildmode=pie`, not the default on Linux); a module with no
`package main` is skipped.

## `code-formatting`

gofmt, gofumpt or goimports; they have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit, or golangci-lint runs with `funlen` enabled.

## `static-analysis`

golangci-lint with linters enabled beyond its defaults (`enable:` or `default: all` in a `.golangci.yml`).

## `security-scanning`

gosec.

## `dependency-management`

A module that requires others commits `go.sum`. `go mod vendor` output is not third-party code committed by hand.

## `dependency-audit`

govulncheck.

## `committed-artifacts`

`*.test`, `*.out` and a top-level `bin/`.

## `vcs-ignore`

`*.test` or `*.out`.
