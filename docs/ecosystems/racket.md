# Racket

Learn more: [Racket](https://racket-lang.org/).

Recognised by `.rkt` sources and by a package's `info.rkt`, the build system (raco pkg); once the project is known to
be Racket, `.rktl` files are Racket too, and Scribble documents (`.scrbl`) and `.rktd` data are files of the
ecosystem with no language of their own. `compiled/` directories are build trees.

## `tests-run`

rackunit tests, in a `(module+ test …)` submodule or a module that requires rackunit, run by `raco test` (or by
`raco cover`, which runs them instrumented). `jackfirth/racket-package-ci-action` installs the package and runs
`raco test --package` on it.

## `coverage`

`raco cover` measures expression coverage, the finest Racket has (`-f codecov` or `-f coveralls` uploads it).

## `platform-matrix`

The toolchains are Racket versions with their variant: Bogdanp/setup-racket's `version` (`8.14`, `stable`,
`current`) and `variant` (`CS`, `BC`), counted after its own `uses:` line only, since every action has a `version`
input; a matrix key `racket-version` or `racket`; a `racket/racket` image. A job naming both runs `8.14 BC`; the
version's default variant (CS from Racket 8.0, BC before) is not named, so `8.14` with `CS` or with no variant is one
version, `8.14`.

## `code-formatting`

`raco fmt -i` rewrites the files, which enforces the style where the job fails on `git diff --exit-code` or commits
the changes; `raco fmt` without `-i` only prints the formatted code. The formatter has one style.

## `static-analysis`

Resyntax, the Racket refactoring linter (`racket -l- resyntax/cli analyze`, or `raco resyntax analyze` and `fix`),
which typed-racket and scribble run on every pull request. It reports, as a review or a scheduled pull request of its
fixes, and never fails the build, so it is an advisory analyser: running it is a warning, not a pass. No Racket linter
the validator knows can fail the build, so a Racket project warns at best; one that runs none fails.

## `license`

The `license` an `info.rkt` declares, an SPDX expression (`(define license '(Apache-2.0 OR MIT))`).

## `committed-artifacts`

The `compiled/` directories (`.zo` and `.dep` files) raco writes beside each module.

## `vcs-ignore`

`compiled/`.

## Not judged

Racket's compiler reports no warnings worth a practice (`compiler-warnings`, `warnings-as-errors`); it is
dynamically typed, Typed Racket aside (`type-checking`); no code security scanner, dependency auditor, function
length limiter, fuzzer or mutation testing tool the validator knows reads Racket; a package's dependencies are
resolved by the catalog without a lock file (`dependency-management`).
