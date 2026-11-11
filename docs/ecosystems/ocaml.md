# OCaml

Recognised by `.ml` and `.mli` sources (and, once the project is known to be OCaml, ocamllex `.mll` and Menhir `.mly`
grammars, Eliom modules, cram tests `.t` and odoc pages `.mld`), and by its build systems: dune (`dune-project`, the
`dune` files, `dune-workspace`) and opam (`*.opam`, or an `opam` file). `_build` beside `dune-project` and a local
switch `_opam` are build trees. `opam exec -- dune build` runs dune in the switch.

dune's `dev` profile, the default, compiles with a strict warning set (`:standard`, which is `-w @1..3@5..28@30..39…
-strict-sequence -strict-formats`) and makes those warnings errors; its `release` profile (`--profile release`,
`--release`, or `-p`, the release build of named packages) turns both off. The warning practices read this from the
dune commands CI runs and from the `(flags …)` fields of the dune files (outside their `(release …)` environment).

## `tests-run`

The `test` and `tests` stanzas, a library's `inline_tests` (ppx_expect, ppx_inline_test) and `cram` tests the dune
files declare, run by `dune test`, `dune runtest` or `dune build @runtest` (an alias of a directory too).

## `coverage`

bisect_ppx, which instruments every branch point: `dune test --instrument-with bisect_ppx` (or `BISECT_ENABLE=yes`,
the older way), or `bisect-ppx-report`, which writes the report.

## `platform-matrix`

The toolchains are OCaml compiler versions: ocaml/setup-ocaml's `ocaml-compiler` (`5.2`, `4.14.x`, or a package,
`ocaml-base-compiler.5.2.0`), an `ocaml/opam:<distro>-ocaml-<version>` image, or `opam switch create`.

## `compiler-warnings`

CI builds and tests in dune's dev profile, and no `(flags …)` field of a dune file leaves out `:standard` (where the
profile's warnings come from) or turns them off with `-w -a`; or a compiler command line passes `-w +a`.

## `warnings-as-errors`

The dev profile makes its warnings errors, so the same, unless a `(flags …)` field adds `-warn-error -a`; or a
command line passes `-warn-error +a`. A project that CI builds only with `--profile release` or `-p` fails.

## `code-formatting`

ocamlformat: `dune build @fmt` fails on a file it would change (with `--auto-promote`, or as `dune fmt`, it rewrites
instead), as does `ocamlformat --check`. A `.ocamlformat` naming the version is required: ocamlformat refuses to run
without one.

## `security-scanning`

semgrep, which reads OCaml; CodeQL and GitLab SAST do not.

## `committed-artifacts`

`_build/`, compiled interfaces and objects (`*.cmi`, `*.cmo`, `*.cmx`, `*.cma`, `*.cmxa`, `*.cmxs`, `*.cmt`), and the
local switch `_opam/`.

## `vcs-ignore`

`_build/` and `_opam/`.

## Not judged

OCaml is statically typed (`type-checking`) and compiles memory-safe code (`hardening`); dune's profiles are warning
settings rather than build types (`ci-build-types`); no dependency auditor reads opam files, and opam's lock files
(`opam lock`) are too little used to ask for (`dependency-management`, `dependency-audit`); no static analyzer besides
the compiler's warnings, function length limiter, fuzzer or mutation testing tool the validator knows measures OCaml.
