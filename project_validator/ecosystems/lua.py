"""Lua (and Luau): packaged with LuaRocks, judged by the Lua versions CI runs and by the tools it runs on the code:
busted, luacov, StyLua, luacheck, selene and the Lua language server."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, analysed, analyzer, type_checked, type_checker
from project_validator.facts.arguments import has_option, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either, starts, when
from project_validator.text import pattern
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

LUA = frozenset({"Lua"})

# A rockspec names the package; `rockspecs/` keeps the ones of past versions.
LUAROCKS = BuildSystem(name="LuaRocks", files=("*.rockspec",), languages=LUA)


# --- Tests and coverage -------------------------------------------------------------------------------------------

# busted looks for `_spec` files under spec/; Neovim plugins keep plenary's busted specs under tests/.
BUSTED_SPECS = TestFiles(
    name="busted specs (spec/**/*_spec.lua)",
    languages=LUA,
    path=re.compile(r"(?:^|/)(?:spec|tests?)/.+_spec\.lua$"),
    contains=re.compile(r"\b(?:describe|it)\s*\("),
)


def _plenary(command: Command) -> bool:
    """`nvim --headless -c "PlenaryBustedDirectory tests"`: plenary.nvim's busted, inside Neovim."""
    argv = resolved(command)
    return argv[:1] == ("nvim",) and any("PlenaryBusted" in word for word in argv)


def _runs_busted(command: Command) -> bool:
    return starts(("busted",), ("luarocks", "test"))(command) or _plenary(command)


BUSTED = test_runner(
    name="busted",
    languages=LUA,
    how="busted (or luarocks test)",
    runs=lambda command, _facts: tested() if _runs_busted(command) else None,
    tests=tests_of(BUSTED_SPECS.name),
)

# `.busted` is Lua: `return { default = { coverage = true } }` turns luacov on for every run.
_BUSTED_COVERAGE = re.compile(r"\bcoverage\s*=\s*(true)\b")


def _read_busted(path: str, text: str) -> Iterator[Setting]:
    return matched_settings("busted", path, text, {"coverage": (_BUSTED_COVERAGE, True)})


BUSTED_SETTINGS = SettingsReader(name="busted", files=(".busted",), read=_read_busted)


def _luacov(command: Command, facts: Facts) -> Run | None:
    """luacov counts lines: `busted --coverage` (or `-c`, or `coverage = true` in `.busted`), `luarocks test --
    --coverage`, or `luacov` itself, which writes the report."""
    argv = resolved(command)
    if starts_with(argv, ("luacov",)) is not None:
        return measured(Granularity.LINE)
    if not _runs_busted(command):
        return None
    if has_option(argv, "--coverage", "-c"):
        return measured(Granularity.LINE)
    configured = facts.where(Setting, tool="busted", key="coverage")
    return measured(Granularity.LINE, read=configured) if configured else None


LUACOV = coverage_tool(
    name="luacov",
    languages=LUA,
    can={Granularity.LINE: "busted --coverage (luacov)"},
    measures=_luacov,
    reads=("busted",),
)


# --- Formatting ---------------------------------------------------------------------------------------------------

STYLUA_SETTINGS = file_reader("StyLua", ("stylua.toml", ".stylua.toml"))

# StyLua has a default style; its settings file is optional. The pre-commit hooks are `stylua` (rewrites) and
# `stylua-check`.
STYLUA = format_tool(
    name="StyLua",
    languages=LUA,
    can={Enforcement.CHECK: "stylua --check .", Enforcement.APPLY: "stylua ."},
    formats=either(flagged(("stylua",), checks=("--check", "-c")), flagged(("stylua-check",), checks=())),
    style=defined_by(files=(STYLUA_SETTINGS.name,)),
)
STYLUA_ACTION = Action(
    name="JohnnyMorganz/stylua-action", runs=lambda inputs: (("stylua", *shlex.split(inputs.get("args", ""))),)
)


# --- Warnings, analysis and type checking ----------------------------------------------------------------------------

# The Lua interpreter compiles without warnings; the linters report what other compilers warn about. luacheck exits
# non-zero on a warning, so running one is the strict set and warnings as errors at once.
LUACHECK = pattern("luacheck", r"\bluacheck\b")
SELENE = pattern("selene", r"\bselene\b")

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=LUA,
    requirements=always(required(LUACHECK, in_files=False), required(SELENE, in_files=False)),
    any_one=True,
    words=Wording(kind="Lua linters", hint="run luacheck (with a .luacheckrc) or selene (with a selene.toml) in CI"),
)

LUACHECK_SETTINGS = file_reader("luacheck", (".luacheckrc",))
SELENE_SETTINGS = file_reader("selene", ("selene.toml",))

LUACHECK_ANALYZER = analyzer(
    name="luacheck",
    languages=LUA,
    how="luacheck .",
    analyses=when(starts(("luacheck",)), analysed),
    rules=defined_by(files=(LUACHECK_SETTINGS.name,)),
)
# selene needs a `selene.toml` naming its standard library (`std = "lua54"`).
SELENE_ANALYZER = analyzer(
    name="selene",
    languages=LUA,
    how="selene .",
    analyses=when(starts(("selene",)), analysed),
    rules=defined_by(files=(SELENE_SETTINGS.name,), default=False),
)
LUACHECK_ACTION = Action(
    name="lunarmodules/luacheck", runs=lambda inputs: (("luacheck", *shlex.split(inputs.get("args", "."))),)
)

LUALS_SETTINGS = file_reader("lua-language-server", (".luarc.json", ".luarc.jsonc"))

# The Lua language server checks LuaCATS annotations (`---@param`); luau-analyze checks Luau's own types.
LUALS = type_checker(
    name="lua-language-server",
    languages=LUA,
    can={Strictness.CHECKS: "lua-language-server --check . (with LuaCATS annotations)"},
    checks=when(starts(("lua-language-server",)), lambda: type_checked(strict=False)),
    configuration=defined_by(files=(LUALS_SETTINGS.name,)),
)
LUAU_ANALYZE = type_checker(
    name="luau-analyze",
    languages=LUA,
    can={Strictness.CHECKS: "luau-analyze ."},
    checks=when(starts(("luau-analyze",)), lambda: type_checked(strict=False)),
)

# semgrep reads Lua; CodeQL and GitLab SAST do not.
SECURITY_SCANNERS = tuple(tool for tool in multi_language_scanners(LUA) if tool.name == "semgrep")

FUNCTION_LENGTH_LIMITERS = function_length_limiters(LUA)


# --- Outputs -------------------------------------------------------------------------------------------------------

ROCKS_TREE = BuildOutput(
    languages=LUA,
    name="the local rocks tree",
    globs=ignored_at_top_level(r"lua_modules|\.luarocks"),
    paths=(*directories("lua_modules"), *directories(".luarocks")),
    hint="consider ignoring lua_modules/ and .luarocks/ (luarocks init writes them)",
    artifacts=("lua_modules/", ".luarocks/"),
)
LUACOV_OUTPUT = BuildOutput(
    languages=LUA,
    name="luacov's output",
    globs=ignored_at_top_level(r"luacov\.\*\.out|luacov\.(?:stats|report)\.out|\*\.out"),
    paths=("luacov.stats.out", "luacov.report.out"),
    hint="consider ignoring luacov.*.out",
    artifacts=("luacov.stats.out", "luacov.report.out"),
)


# --- Recognition and toolchains -----------------------------------------------------------------------------------

# leafo/gh-actions-lua's `luaVersion`: `5.4`, `5.1.5`, `luajit-2.1`, `luajit-openresty`.
_LUA_VERSION = r"(5\.\d(?:\.\d)?|luajit(?:-[\w.-]+)?)"

LUA_ECOSYSTEM = Ecosystem(
    label="Lua",
    languages=LUA,
    build_systems=(LUAROCKS,),
    source_suffixes={".lua": "Lua", ".luau": "Lua"},
    toolchain=toolchain_patterns(
        "Lua",
        version=_LUA_VERSION,
        inputs=("luaVersion", "lua-version"),
        images=("nickblah/lua",),
        # The tools that run on a Lua interpreter; StyLua, selene and the language server are binaries of their own.
        commands=r"\bbusted\b|\bluarocks\b|\bluacheck\b|\bluacov\b|\bgh-actions-lua\b|\blua\s+\S+\.lua\b",
    ),
    ci_usage=re.compile(r"\bstylua\b|\bselene\b|\blua-language-server\b|\bluau-analyze\b"),
)

LUA_VERSIONS = versions_axis("Lua version", "Lua", LUA)
