# Emacs Lisp

Recognised by `.el` sources and by a package's build files: `Eask`, `Cask`, or package.el's `<name>-pkg.el`. Eask's
`.eask/` and Cask's `.cask/`, where the dependencies are installed, are build trees; a byte-compiled `.elc` is a file
of the ecosystem with no language of its own.

## `tests-run`

ERT (`ert-deftest`) or Buttercup (`describe`/`it`) tests under `test/` (or `*-test.el`), run by `eask test ert`,
`eask test buttercup`, `eask test ert-runner`, `cask exec ert-runner` or `cask exec buttercup`, the runners
themselves, `makem.sh test`, or Emacs in batch mode (`emacs -batch -l test/shop-test.el -f
ert-run-tests-batch-and-exit`).

## `coverage`

undercover.el counts the lines the tests run: set up in the test files (`(undercover "*.el")`), or on the command
line (`UNDERCOVER_FORCE`), when the tests run.

## `platform-matrix`

The toolchains are Emacs versions: the `version` of purcell/setup-emacs or jcs090218/setup-emacs (counted after
their own `uses:` line only, since every action has a `version` input), a matrix key `emacs-version` or `emacs`, or a
`silex/emacs` image.

## `compiler-warnings`

package-lint (the package headers and conventions) and checkdoc (the docstrings) both run in CI: `eask lint
package` and `eask lint checkdoc`, or melpazoid, which runs both.

## `warnings-as-errors`

A byte-compiler warning fails the compilation: `eask compile --strict`, or `byte-compile-error-on-warn` set before
`batch-byte-compile` (in CI, the Eask or Cask file, the Makefile or the sources).

## `static-analysis`

package-lint and checkdoc.

## `committed-artifacts`

The byte-compiled `*.elc` files, the generated `*-autoloads.el`, and the tools' `.eask/` and `.cask/`.

## `vcs-ignore`

`*.elc` and `*-autoloads.el`, plus `.eask/` for an Eask package and `.cask/` for a Cask one.

## Not judged

Emacs Lisp has no standard formatter (`code-formatting`), and no type checker, code security scanner, dependency
auditor, fuzzer or mutation testing tool the validator knows; lizard does not parse it (`function-limits`); a package
has no lock file (`dependency-management`); byte-compilation builds no debug or release configuration
(`ci-build-types`, `hardening`, `cxx-extensions`).
