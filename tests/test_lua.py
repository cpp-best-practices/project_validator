"""The Lua profile's rules, judged by the generic checks in the LuaRocks package and plain Lua layouts."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.lua import LUA_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, run_as, temp_project

SPEC = {"spec/shop_spec.lua": 'describe("shop", function()\n  it("adds", function() end)\nend)\n'}
PLENARY_SPEC = {"tests/shop_spec.lua": 'describe("shop", function()\n  it("adds", function() end)\nend)\n'}
LUA_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest]
            lua: ["5.1", "5.4", "luajit-2.1"]
        steps:
          - uses: leafo/gh-actions-lua@v11
            with:
              luaVersion: ${{ matrix.lua }}
          - run: busted
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_lua_and_luau_sources_with_or_without_a_rockspec(self) -> None:
        with temp_project({"lua/shop/init.lua": "", "types.luau": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Lua"}))
        self.assertEqual(structure.build_systems, frozenset())
        with temp_project({"shop-dev-1.rockspec": "", "rockspecs/shop-1.0-1.rockspec": "", "src/shop.lua": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.build_systems, frozenset({"LuaRocks"}))
        self.assertEqual([unit.directory for unit in structure.units], ["."])

    def test_ci_usage(self) -> None:
        for text in ("busted --coverage", "luarocks test", "stylua --check .", "uses: leafo/gh-actions-lua@v11"):
            with self.subTest(text=text):
                self.assertTrue(LUA_ECOSYSTEM.used_by(text))
        self.assertFalse(LUA_ECOSYSTEM.used_by("npm test"))


class LuaTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, LUA_ECOSYSTEM)

    def test_busted_specs_run_by_busted_luarocks_or_plenary(self) -> None:
        for command in ("busted", "luarocks test", 'nvim --headless -c "PlenaryBustedDirectory tests"'):
            with self.subTest(command=command):
                self.assertEqual(self._run(tests_run, {**SPEC, **_ci(command)}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**PLENARY_SPEC, **_ci("busted tests")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**SPEC, **_ci("luacheck .")}).status, Status.WARN)
        helper = {"spec/helper.lua": "return {}\n", **_ci("busted")}
        self.assertEqual(self._run(tests_run, helper).status, Status.FAIL)

    def test_luacov_counts_lines_when_busted_collects(self) -> None:
        for command in ("busted --coverage", "busted -c", "luarocks test -- --coverage", "busted && luacov"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(coverage, _ci(command)), Result.passed("line coverage is reported with luacov")
                )
        configured = {".busted": "return {\n  default = {\n    coverage = true,\n  },\n}\n", **_ci("busted")}
        self.assertEqual(self._run(coverage, configured), Result.passed("line coverage is reported with luacov"))
        self.assertEqual(self._run(coverage, _ci("busted")).status, Status.FAIL)

    def test_stylua_enforces_when_it_checks(self) -> None:
        for command in ("stylua --check .", "stylua -c src"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(code_formatting, _ci(command)), Result.passed("CI enforces the StyLua style")
                )
        configured = {"stylua.toml": 'indent_type = "Spaces"\n', **_ci("stylua --check .")}
        self.assertEqual(
            self._run(code_formatting, configured), Result.passed("stylua.toml is defined and CI runs StyLua")
        )
        self.assertEqual(self._run(code_formatting, _ci("stylua .")).status, Status.FAIL)
        action = github_steps("uses: JohnnyMorganz/stylua-action@v4")
        action[GITHUB_WORKFLOW] = action[GITHUB_WORKFLOW].replace(
            '"uses": "JohnnyMorganz/stylua-action@v4"',
            '"uses": "JohnnyMorganz/stylua-action@v4", "with": {"args": "--check ."}',
        )
        self.assertEqual(self._run(code_formatting, action).status, Status.PASS)
        hooks = {
            ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/JohnnyMorganz/StyLua\n    rev: v2.0.2\n"
            "    hooks:\n      - id: stylua-check\n",
            **_ci("pre-commit run --all-files"),
        }
        self.assertEqual(self._run(code_formatting, hooks).status, Status.PASS)

    def test_luacheck_or_selene_is_the_warning_set(self) -> None:
        self.assertEqual(
            self._run(compiler_warnings, _ci("luacheck .")), Result.passed("strict Lua linters are enabled: luacheck")
        )
        self.assertEqual(self._run(compiler_warnings, _ci("selene .")).status, Status.PASS)
        self.assertEqual(
            self._run(compiler_warnings, github_steps("uses: lunarmodules/luacheck@v1")).status, Status.PASS
        )
        self.assertEqual(self._run(compiler_warnings, _ci("busted")).status, Status.FAIL)

    def test_luacheck_and_selene_are_static_analysis(self) -> None:
        configured = {".luacheckrc": 'std = "lua54"\n', **_ci("luacheck .")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("luacheck (.luacheckrc) runs"))
        self.assertEqual(self._run(static_analysis, _ci("luacheck .")), Result.passed("luacheck runs"))
        selene = {"selene.toml": 'std = "lua54"\n', **_ci("selene .")}
        self.assertEqual(self._run(static_analysis, selene), Result.passed("selene (selene.toml) runs"))
        self.assertEqual(self._run(static_analysis, _ci("selene .")).status, Status.WARN)
        self.assertEqual(self._run(static_analysis, _ci("busted")).status, Status.FAIL)

    def test_the_language_server_type_checks_annotations(self) -> None:
        configured = {".luarc.json": '{"runtime.version": "Lua 5.4"}\n', **_ci("lua-language-server --check src")}
        self.assertEqual(self._run(type_checking, configured).message, "lua-language-server (.luarc.json) runs")
        self.assertEqual(self._run(type_checking, _ci("luau-analyze .")).status, Status.PASS)
        self.assertEqual(self._run(type_checking, _ci("luacheck .")).status, Status.FAIL)

    def test_semgrep_scans_but_codeql_does_not(self) -> None:
        result = self._run(security_scanning, _ci("pipx run semgrep scan --config p/lua --error ."))
        self.assertEqual(result, Result.passed("CI scans the code for security problems with semgrep"))
        codeql = github_steps("uses: github/codeql-action/analyze@v3")
        self.assertEqual(self._run(security_scanning, codeql).status, Status.WARN)

    def test_the_rocks_tree_and_luacov_output_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "lua_modules/\nluacov.*.out\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": ".luarocks/\nluacov.stats.out\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "lua_modules/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_lua_versions_and_implementations(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: LUA_MATRIX})
        self.assertIn("3 Lua version(s) (5.1, 5.4, luajit-2.1)", result.message)
        # StyLua and the language server need no Lua interpreter: a job running only them names no Lua version.
        self.assertIn("0 Lua version(s)", self._run(platform_matrix, _ci("stylua --check .")).message)
        self.assertIn("(default)", self._run(platform_matrix, _ci("busted")).message)
