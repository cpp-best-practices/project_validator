# BEAM

Elixir and Erlang, recognised by `.ex`, `.exs`, `.erl` and `.hrl` sources and by their build tools: Mix (`mix.exs`;
an umbrella's `apps_path` applications are units of their own) and rebar3 (`rebar.config`). A Mix project compiles
the Erlang modules in its `src/` too, so its tests, coverage, Dialyzer and dependency audit count for both languages.

Both tools run tasks, and a command may run several: `mix do format --check-formatted, credo --strict` (or with `+`),
`rebar3 do eunit, ct, cover`, `rebar3 as test cover`. Every rule below is about the task, however it is run. A Mix
alias (`aliases: [lint: ["format --check-formatted", "credo --strict"]]` in `mix.exs`) runs the task lines it lists,
as a package script does, so `mix lint` counts for what `lint` runs.

The compiled-language checks that need a C-family compiler (hardening, build types, extensions, sanitizers) do not
apply, and nor do fuzz testing and mutation testing: no fuzzer or mutation tool for the BEAM is known.

## `tests-run`

ExUnit tests (`test/**/*_test.exs` with `test`, `describe`, `property` or `doctest`) run by `mix test` (or an
excoveralls task, which runs them too); EUnit tests (`*_test()` functions in `.erl` files) or Common Test suites
(`*_SUITE.erl` with `all()`) run by `rebar3 eunit` or `rebar3 ct`. In a Mix project, `mix test` counts for the
Erlang modules too.

## `coverage`

The BEAM's `cover` tool counts lines, so line coverage is what is asked for: `mix test --cover`, excoveralls
(`mix coveralls`, `mix coveralls.json`, `mix coveralls.github`, ...), or `rebar3 cover` (or `rebar3 eunit --cover`,
`rebar3 ct --cover`).

## `platform-matrix`

The toolchains are Erlang/OTP and Elixir versions, named by erlef/setup-beam's `otp-version` and `elixir-version`,
by the `erlang` and `elixir` images (`elixir:1.18.3-otp-27`, `hexpm/elixir:1.18.3-erlang-27.3`), or by a
`-otp-`/`-erlang-` tag. A job that names both runs each Elixir version on each OTP version it names
(`Elixir 1.18 / OTP 27`), so a matrix of Elixir versions on one OTP counts each pairing once.

## `compiler-warnings`

Elixir's compiler warns about everything it knows without being asked, so the strict set is Credo's: `mix credo
--strict` (or `strict: true` in `.credo.exs`). Erlang: the optional warnings in `erl_opts` (`warn_missing_spec`,
`warn_export_vars`, ... in `rebar.config`, or `erlc_options` in `mix.exs`) and elvis (`rebar3 lint` or `elvis rock`).

## `warnings-as-errors`

Elixir: `mix compile --warnings-as-errors` (or `mix test --warnings-as-errors`) in CI, or
`elixirc_options: [warnings_as_errors: true]` in `mix.exs`. Erlang: `warnings_as_errors` in `erl_opts`
(`rebar.config`) or `erlc_options` (`mix.exs`), or `erlc -Werror`.

## `code-formatting`

`mix format --check-formatted`, which fails on a file it would change (plain `mix format` rewrites; `--dry-run` alone
only lists); `.formatter.exs` is where the style is set, with a default. erlfmt for Erlang: `rebar3 fmt --check`
(plain `rebar3 fmt` rewrites) or `erlfmt --check`; it has one style.

## `static-analysis`

Credo (`mix credo`, with its checks in `.credo.exs`) for Elixir; elvis (`rebar3 lint` or `elvis rock`, with
`elvis.config`) or `rebar3 xref` for Erlang.

## `type-checking`

Dialyzer, run as `mix dialyzer` (dialyxir) or `rebar3 dialyzer`, for both languages; its optional warnings
(`dialyzer: [flags: [:underspecs, :unmatched_returns]]` in `mix.exs`, `{dialyzer, [{warnings, [...]}]}` in
`rebar.config`) are its strict mode, a bonus. eqWAlizer (`elp eqwalize-all`) counts for Erlang.

## `security-scanning`

Sobelow (`mix sobelow --exit`, or the `sobelow/action` action) finds the security issues of Phoenix applications;
GitLab SAST and semgrep count too. Nothing scans Erlang, and CodeQL reads neither language, so an Erlang-only project
is skipped.

## `dependency-audit`

mix_audit (`mix deps.audit`), or `mix hex.audit` for retired packages; osv-scanner, trivy or snyk count too.

## `dependency-management`

A `mix.exs` that declares dependencies commits `mix.lock`; a `rebar.config` with `deps` commits `rebar.lock`. Both
hold each package's hash.

## `committed-artifacts`

`_build/` (and `.beam` files), a Mix project's `deps/`, and crash dumps (`erl_crash.dump`, `rebar3.crashdump`).

## `vcs-ignore`

`_build/`, `deps/` (Mix) and `erl_crash.dump`: the `mix new` and `rebar3 new` ignore files have all three.

## `function-limits`

lizard parses Erlang, so an Erlang project runs it with a length limit. No tool measures Elixir functions, so
Elixir-only projects are skipped.
