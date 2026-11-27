# Gleam

Learn more: [Gleam](https://gleam.run/).

Recognised by `.gleam` sources and the `gleam` build tool (`gleam.toml`), which compiles a package to Erlang or
JavaScript. A CI job uses Gleam when it runs `gleam` or sets up a `gleam-version` (erlef/setup-beam). A package's
Erlang or JavaScript FFI modules beside its `.gleam` sources are judged by their own profiles.

## `tests-run`

The test modules under `test/` (gleeunit's or startest's, or modules with `pub fn …_test()` functions), run by
`gleam test`.

## `code-formatting`

`gleam format --check`, which fails on a file it would change; Gleam has one style, its formatter's.

## `vcs-ignore`

`build/`, where gleam writes the compiled packages, is ignored.

## `committed-artifacts`

Nothing under `build/` is committed.

## Not judged

The Gleam compiler's warnings are always on, and no linter or type checker beyond the compiler is in common use, so
`compiler-warnings`, `static-analysis` and `type-checking` have nothing to ask; the other checks have no tool for Gleam
and are skipped.
