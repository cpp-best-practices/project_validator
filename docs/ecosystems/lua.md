# Lua

Recognised by `.lua` (and Luau's `.luau`) sources and by LuaRocks' `*.rockspec` files, the one build system; a
project without a rockspec (a Neovim plugin, a game's scripts) is Lua all the same. The interpreter compiles without
warnings, so the linters stand in for a compiler's warning set.

The compiled-language checks that need a C-family compiler (hardening, build types, extensions, sanitizers) do not
apply, and nor do fuzz testing, mutation testing, dependency management (LuaRocks has no lockfile in common use),
dependency audit (no auditor reads rockspecs) and `warnings-as-errors` (luacheck and selene fail on a warning already).

## `tests-run`

busted specs (`describe`/`it` in `spec/**/*_spec.lua`, or under `tests/` for plenary.nvim), run by `busted`,
`luarocks test` (which runs the rockspec's busted test suite), or `nvim --headless -c "PlenaryBustedDirectory tests"`.

## `coverage`

luacov counts lines, the most anything measures for Lua: `busted --coverage` (or `-c`, or `coverage = true` in
`.busted`), `luarocks test -- --coverage`, or `luacov` itself writing the report.

## `platform-matrix`

The toolchains are Lua versions and implementations (`5.1` to `5.4`, `luajit-2.1`, `luajit-openresty`), named by
leafo/gh-actions-lua's `luaVersion` or a `lua-version` input.

## `compiler-warnings`

luacheck (with its `.luacheckrc`) or selene (with its `selene.toml`) runs in CI; either exits non-zero on a warning.

## `code-formatting`

StyLua: `stylua --check` fails on a file it would change, plain `stylua` rewrites; the `JohnnyMorganz/stylua-action`
action with `args: --check .`, and the `stylua` and `stylua-check` pre-commit hooks. `stylua.toml` is optional, as
StyLua has a default style.

## `static-analysis`

luacheck, with the globals and rules of `.luacheckrc`, or selene, which needs a `selene.toml` naming its standard
library (`std = "lua54"`).

## `type-checking`

The Lua language server checking LuaCATS annotations (`lua-language-server --check .`, with `.luarc.json`), or
luau-analyze for Luau.

## `security-scanning`

semgrep, which reads Lua; CodeQL and GitLab SAST do not.

## `committed-artifacts`

The local rocks tree (`lua_modules/`, `.luarocks/`) and luacov's output (`luacov.stats.out`, `luacov.report.out`).

## `vcs-ignore`

`lua_modules/` or `.luarocks/`, and `luacov.*.out`.

## `function-limits`

lizard parses Lua, so CI runs it with a length limit.
