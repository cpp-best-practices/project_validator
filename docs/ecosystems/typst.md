# Typst

Learn more: [Typst](https://typst.app/).

Recognised by `.typ` sources. A CI job uses Typst when it runs `typst`, typstyle or typstfmt, or installs it with
`typst-community/setup-typst`.

## `tests-run`

CI compiles the documents: `typst compile main.typ`, or tytanic's `tt run`, which compiles each `tests/**/test.typ`
against its reference. The documents themselves are what defines the tests.

## `code-formatting`

typstyle (`--check`, which fails on a file it would change; `-i` rewrites, as typstyle-rs/typstyle-action does, which
enforces the style with a later `git diff --exit-code`) or typstfmt (`--check`), each with its one style.

## Not judged

Typst has no lint beyond its compiler, so `compiler-warnings` and `static-analysis` have nothing to ask; compiling
leaves only the PDF, so `vcs-ignore` has nothing either; `coverage` has no meaning for a document. The other checks
have no tool for Typst and are skipped.
