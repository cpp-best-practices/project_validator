# Shell

Shell and PowerShell. Recognised by `.sh`, `.bash`, `.zsh` and `.bats` sources (Shell), by `.ps1` and `.psm1` sources (PowerShell), and by
a script without a suffix whose shebang names a shell (`#!/usr/bin/env bash`) or `pwsh`. A module manifest (`.psd1`)
is data about a module and counts for no language. There is no build system.

A project's helper scripts make Shell one of its languages, judged in the units they are in, like any other source
would; `--auxiliary shell`, or `--auxiliary scripts/`, dials that back to warnings that say so. The policies hold
either way: a script CI runs deserves shellcheck.

## `tests-run`

Shell: bats tests (`*.bats` with `@test`), shellspec specs (`spec/*_spec.sh` with `Describe` or `It`) or shunit2
tests (`*_test.sh` sourcing shunit2), and CI runs them: `bats tests`, `shellspec`, or the shunit2 script itself
(`./tests/shop_test.sh`, `bash tests/shop_test.sh`, `shunit2 tests/shop_test.sh`).

PowerShell: Pester tests (`*.Tests.ps1` with `Describe` or `It`) that `Invoke-Pester` runs.

## `coverage`

Shell: kcov reports line coverage (`kcov --include-path=src coverage bats tests`, or `shellspec --kcov`); kcov is a
wrapper, so the test run inside it counts for `tests-run` too. Nothing measures branches in a shell, so lines are what
is required.

PowerShell: Pester's code coverage counts the commands run: `Invoke-Pester -CodeCoverage <scripts>`, `-CI` (which
turns it on), or `CodeCoverage.Enabled = $true` in the configuration a script builds (`New-PesterConfiguration`), read
heuristically from `.ps1` and `.psd1` files. Statements are the finest granularity, so they are what is required.

## `code-formatting`

Shell: shfmt checks the formatting with `-d` or `-l` (`shfmt -d .`) and applies it with `-w`. It has a default style
and reads the project's from `.editorconfig`. No tool checks PowerShell formatting without rewriting the files, so the
check does not apply to PowerShell.

## `static-analysis`

Shell: shellcheck (`shellcheck <scripts>`, or the `ludeeus/action-shellcheck` and `reviewdog/action-shellcheck`
actions), with its settings in `.shellcheckrc`.

PowerShell: PSScriptAnalyzer (`Invoke-ScriptAnalyzer -Path . -Recurse`, or `microsoft/psscriptanalyzer-action`),
with its settings in `PSScriptAnalyzerSettings.psd1`.

## `compiler-warnings`

A shell has no compiler warnings; its lints stand in. Shell: shellcheck runs in CI. PowerShell: PSScriptAnalyzer runs
in CI.

## `warnings-as-errors`

Shell: shellcheck fails on any finding, so running it is enough. PowerShell: `Invoke-ScriptAnalyzer -EnableExit`, so
that a finding fails the job.

## Not judged

`platform-matrix` needs an axis besides the OS (a compiler, a toolchain version); shells have none CI names, and
whether a PowerShell job runs Windows PowerShell 5.1 or PowerShell 7 is a step's `shell`, which the jobs do not record
yet. `function-limits`, `hardening`, `dependency-audit` and the others have no tool for the shells and are skipped.
