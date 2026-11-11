# R

Recognised by `.R` sources (and, once the project is known to be R, `.r` files, which REBOL uses too; R Markdown,
Quarto, Sweave, Rd and RStudio project files are files of the ecosystem with no language of their own) and by an R
package's `DESCRIPTION` with a `Package:` field. `<package>.Rcheck` directories are build trees.

CI runs R code in three ways, read alike: `Rscript -e "covr::codecov()"` (or `R -e`), a step whose
`shell: Rscript {0}` runs its script, and the r-lib/actions, whose `check-r-package` runs rcmdcheck with its inputs.

## `tests-run`

testthat's files (`test_that()` in `tests/testthat/test-*.R`) or tinytest's (`inst/tinytest/test_*.R`), run by
`R CMD check` (which runs the tests), `rcmdcheck::rcmdcheck()` or `r-lib/actions/check-r-package`, `devtools::test()`
or `devtools::check()`, `testthat::test_local()` and its kin, or `tinytest::test_package()`.

## `coverage`

covr counts lines, the finest R has: `covr::package_coverage()`, or the reports and uploads built on it
(`covr::codecov()`, `covr::coveralls()`, `covr::report()`, `covr::to_cobertura()`).

## `platform-matrix`

The toolchains are R versions: r-lib/actions/setup-r's `r-version` (`release`, `devel`, `oldrel-1`, or a version), or
a rocker image (`rocker/r-ver:4.4.1`, `rocker/tidyverse`, `rocker/verse`) or `r-base` image.

## `compiler-warnings`

R has no compiler warnings; lintr's lints stand in. `lintr::lint_package()` runs in CI and fails on a lint, which it
does only with `LINTR_ERROR_ON_LINT=true` (as r-lib's example workflow sets it) or `error_on_lint = TRUE`; the `lintr`
pre-commit hook fails by itself.

## `warnings-as-errors`

The package check fails on a WARNING (or a NOTE): `rcmdcheck::rcmdcheck(error_on = "warning")`, which
`r-lib/actions/check-r-package` does by default. `R CMD check` alone fails only on an ERROR.

## `code-formatting`

air: `air format --check .` fails on a file it would change, plain `air format .` rewrites; `air.toml` is optional.
styler (`styler::style_pkg()`, or the `style-files` pre-commit hook) only rewrites, which counts where the job fails
on `git diff --exit-code` or commits the changes.

## `static-analysis`

lintr, with the linters `.lintr` names (its defaults without).

## `function-limits`

lizard parses R, so CI runs it with a length limit.

## `committed-artifacts`

`.Rhistory`, `.RData`, `.Rproj.user/` and `*.Rcheck/`.

## `vcs-ignore`

`.Rhistory`, `.RData`, `.Rproj.user/` and `*.Rcheck/`, each.

## Not judged

R is interpreted, so `hardening`, `cxx-extensions` and `ci-build-types` do not apply, and nor does `type-checking`;
no code security scanner or dependency auditor the validator knows reads R, and a lock file (`renv.lock`) belongs to
an analysis or an application rather than a package (`dependency-management`); no fuzzer or mutation testing tool
the validator knows runs R tests.
