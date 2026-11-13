# Typst

Recognised by `.typ` sources. A CI job uses Typst when it runs `typst`, typstyle or typstfmt, or installs it with
`typst-community/setup-typst`.

## `tests-run`

CI compiles the documents: `typst compile main.typ`. The documents themselves are what defines the tests.

## `code-formatting`

typstyle (`--check`, which fails on a file it would change; `-i` rewrites) or typstfmt (`--check`), each with its one
style.

## Not judged

Typst has no lint beyond its compiler, so `compiler-warnings` and `static-analysis` have nothing to ask; compiling
leaves only the PDF, so `vcs-ignore` has nothing either; `coverage` has no meaning for a document. The other checks
have no tool for Typst and are skipped.
