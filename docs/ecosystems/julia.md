# Julia

Recognised by `.jl` sources and by Pkg's `Project.toml` (or `JuliaProject.toml`) naming a package or its
dependencies; another file so named declares no language.

CI runs Julia code in three ways, read alike: `julia -e 'using Pkg; Pkg.test()'`, a step whose
`shell: julia --color=yes {0}` runs its script, and the julia-actions, each standing for the julia command it runs
(`julia-runtest` is `Pkg.test()` with coverage and the `depwarn` it is given).

## `tests-run`

`@test` and `@testset` in `test/runtests.jl` (or another file under `test/`), run by `Pkg.test()`,
`julia-actions/julia-runtest` or `julia test/runtests.jl`.

## `coverage`

Julia counts lines, the finest it has: `julia --code-coverage` (julia-runtest's default), `Pkg.test(coverage = true)`,
or Coverage.jl processing the `.cov` files (`julia-actions/julia-processcoverage`).

## `platform-matrix`

The toolchains are Julia versions: julia-actions/setup-julia's `version` (`1`, `1.10`, `lts`, `pre`, `nightly`; a
`version:` input counts only under setup-julia's `uses:`), a matrix key `julia-version` or `julia`, a `julia:` image,
or `juliaup add`.

## `compiler-warnings`

Julia compiles without warnings; Aqua.jl's checks of the package (method ambiguities, stale dependencies, type
piracy, undefined exports) stand in: `Aqua.test_all(YourPackage)` in `test/runtests.jl`.

## `warnings-as-errors`

Deprecation warnings fail the tests: `--depwarn=error` on the julia command line, or julia-runtest's
`depwarn: error`.

## `type-checking`

JET.jl checks the package's types when the tests call `JET.test_package(YourPackage)` (or `report_package`) and CI runs
the tests.

## `code-formatting`

JuliaFormatter: `format(".")` rewrites, and checks when the script fails on a file it changed
(`format(".") || exit(1)`, what `julia-actions/julia-format` does, or a `git diff --exit-code` after it);
`.JuliaFormatter.toml` picks a style other than the default. Runic: `runic --check .` (or `fredrikekre/runic-action`)
checks, `runic --inplace .` rewrites.

## `security-scanning`

semgrep, which reads Julia; CodeQL and GitLab SAST do not.

## `committed-artifacts`

The coverage files `--code-coverage` writes beside the sources (`*.jl.cov`, `*.jl.*.cov`) and the allocation files
of `--track-allocation` (`*.jl.mem`).

## `vcs-ignore`

`*.jl.cov` (or `*.jl.*.cov`) and `*.jl.mem`. A package's `Manifest.toml` is a lock file rather than a build output,
left to `dependency-management`.

## Not judged

Julia compiles memory-safe code (`hardening`, `cxx-extensions`, `ci-build-types`); no static analyzer besides Aqua
and JET, dependency auditor, function length limiter (lizard does not parse Julia), fuzzer or mutation testing tool
the validator knows reads Julia; `[compat]` entries and a committed `Manifest.toml` for applications belong to
`dependency-management`, not judged for Julia yet.
