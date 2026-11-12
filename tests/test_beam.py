"""The BEAM profile's rules, judged by the generic checks in the Mix and rebar3 project layouts."""

from __future__ import annotations

import unittest
from unittest import mock

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.beam import BEAM, mix_aliases, mix_tasks, rebar3_tasks
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, run_in_layout, temp_project, uses

MIX = "Mix Elixir"
REBAR3 = "rebar3 Erlang"
EXUNIT = {"test/shop_test.exs": 'defmodule ShopTest do\n  use ExUnit.Case\n  test "adds" do\n  end\nend\n'}
EUNIT = {
    "test/shop_tests.erl": '-module(shop_tests).\n-include_lib("eunit/include/eunit.hrl").\n\n'
    "add_test() ->\n    ?assertEqual(2, 1 + 1).\n"
}
SUITE = {"test/shop_SUITE.erl": "-module(shop_SUITE).\n-export([all/0]).\n\nall() -> [adds].\n"}
MIX_DEPS = {"mix.exs": 'defmodule Shop.MixProject do\n  use Mix.Project\n  defp deps, do: [{:jason, "~> 1.4"}]\nend\n'}
REBAR_DEPS = {"rebar.config": '{deps, [{jsx, "3.1.0"}]}.\n'}
ELIXIR_OTP_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest]
            elixir: ["1.17", "1.18"]
            otp: ["26", "27"]
        steps:
          - uses: erlef/setup-beam@v1
            with:
              otp-version: ${{ matrix.otp }}
              elixir-version: ${{ matrix.elixir }}
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class TaskParsingTests(unittest.TestCase):
    def test_mix_runs_one_task_or_several_with_do(self) -> None:
        self.assertEqual(mix_tasks(("mix", "test", "--cover")), (("test", "--cover"),))
        self.assertEqual(
            mix_tasks(("mix", "do", "format", "--check-formatted,", "credo", "--strict")),
            (("format", "--check-formatted"), ("credo", "--strict")),
        )
        self.assertEqual(mix_tasks(("mix", "do", "deps.get", "+", "test")), (("deps.get",), ("test",)))
        self.assertEqual(mix_tasks(("mix",)), ())
        self.assertEqual(mix_tasks(("npm", "test")), ())

    def test_rebar3_runs_tasks_under_a_profile_or_with_do(self) -> None:
        self.assertEqual(rebar3_tasks(("rebar3", "ct")), (("ct",),))
        self.assertEqual(rebar3_tasks(("rebar3", "as", "test", "cover")), (("cover",),))
        self.assertEqual(
            rebar3_tasks(("rebar3", "do", "eunit", "--cover,", "ct", ",", "cover")),
            (("eunit", "--cover"), ("ct",), ("cover",)),
        )
        self.assertEqual(rebar3_tasks(("rebar3",)), ())

    def test_mix_aliases_are_read_from_the_aliases_function_or_inline(self) -> None:
        function = (
            '  def project do\n    [app: :shop, elixirc_paths: ["lib"], aliases: aliases()]\n  end\n\n'
            '  defp aliases do\n    [\n      setup: ["deps.get", "ecto.setup"],\n'
            '      ci: ["format --check-formatted", "credo --strict", &run/1],\n      lint: "credo"\n    ]\n  end\n'
        )
        self.assertEqual(
            mix_aliases(function),
            {
                "setup": ("deps.get", "ecto.setup"),
                "ci": ("format --check-formatted", "credo --strict"),
                "lint": ("credo",),
            },
        )
        inline = '[app: :shop, aliases: [test: ["ecto.create --quiet", "test"]]]'
        self.assertEqual(mix_aliases(inline), {"test": ("ecto.create --quiet", "test")})
        self.assertEqual(mix_aliases('[app: :shop, elixirc_paths: ["lib"]]'), {})
        # A list that never closes (a file cut short) is read to its end.
        self.assertEqual(mix_aliases('defp aliases do\n  [lint: ["credo"]'), {"lint": ("credo",)})


class RecognitionTests(unittest.TestCase):
    def test_an_umbrella_project_has_an_application_per_unit(self) -> None:
        files = {
            "mix.exs": "defmodule Shop.Umbrella.MixProject do\n  use Mix.Project\n"
            '  def project, do: [apps_path: "apps"]\nend\n',
            "apps/web/mix.exs": "defmodule Web.MixProject do\nend\n",
            "apps/web/lib/web.ex": "",
            "apps/core/mix.exs": "defmodule Core.MixProject do\nend\n",
            "apps/core/lib/core.ex": "",
        }
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Elixir"}))
        self.assertEqual(sorted(unit.directory for unit in structure.units), [".", "apps/core", "apps/web"])

    def test_ci_usage(self) -> None:
        for text in ("mix test --cover", "rebar3 as test ct", "erlc -Werror src/*.erl", "uses: erlef/setup-beam@v1"):
            with self.subTest(text=text):
                self.assertTrue(uses(BEAM, text))
        for text in ("npm run mix", "a mix of things", "npx mix --production"):
            with self.subTest(text=text):
                self.assertFalse(uses(BEAM, text))


class ElixirTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, MIX, selected, files)

    def test_mix_format_enforces_the_formatting_when_it_checks(self) -> None:
        checks = self._run(code_formatting, {".formatter.exs": "[inputs: []]\n", **_ci("mix format --check-formatted")})
        self.assertEqual(checks, Result.passed(".formatter.exs is defined and CI runs mix format"))
        self.assertEqual(self._run(code_formatting, _ci("mix format --check-formatted")).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("mix do format --check-formatted, test")).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("mix format")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("mix format --dry-run")).status, Status.FAIL)

    def test_an_alias_runs_the_task_lines_it_lists(self) -> None:
        aliases = {
            "mix.exs": "defmodule Shop.MixProject do\n  use Mix.Project\n  def project, do: [aliases: aliases()]\n"
            '  defp aliases, do: [lint: ["format --check-formatted", "credo --strict"], '
            'test: ["ecto.create", "test"]]\n'
            "end\n"
        }
        self.assertEqual(self._run(code_formatting, {**aliases, **_ci("mix lint")}).status, Status.PASS)
        self.assertEqual(self._run(compiler_warnings, {**aliases, **_ci("mix lint")}).status, Status.PASS)
        # An alias that runs the task it is named after runs it once.
        self.assertEqual(self._run(tests_run, {**aliases, **EXUNIT, **_ci("mix test")}).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, {**aliases, **_ci("mix test")}).status, Status.FAIL)

    def test_exunit_tests_run_by_mix_test(self) -> None:
        self.assertEqual(self._run(tests_run, {**EXUNIT, **_ci("mix test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**EXUNIT, **_ci("mix coveralls.github")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**EXUNIT, **_ci("mix compile")}).status, Status.WARN)
        no_tests = {"test/shop_test.exs": "defmodule ShopTest do\n  use ExUnit.Case\nend\n", **_ci("mix test")}
        self.assertEqual(self._run(tests_run, no_tests).status, Status.FAIL)
        elsewhere = {"lib/shop_test.exs": 'test "adds" do\nend\n', **_ci("mix test")}
        self.assertEqual(self._run(tests_run, elsewhere).status, Status.FAIL)

    def test_coverage_is_lines_from_cover_or_excoveralls(self) -> None:
        self.assertEqual(self._run(coverage, _ci("mix test")).status, Status.FAIL)
        result = self._run(coverage, _ci("mix test --cover"))
        self.assertEqual(
            result,
            Result.passed(
                "line coverage is reported with mix test --cover",
                "consider failing CI when line coverage falls below a threshold",
            ),
        )
        for task in ("mix coveralls", "mix coveralls.json", "mix coveralls.github"):
            with self.subTest(task=task):
                self.assertEqual(self._run(coverage, _ci(task)).status, Status.PASS)

    def test_credo_strict_is_the_warning_set(self) -> None:
        result = self._run(compiler_warnings, _ci("mix credo --strict"))
        self.assertEqual(result, Result.passed("strict Elixir linters are enabled: mix credo --strict"))
        self.assertEqual(self._run(compiler_warnings, _ci("mix credo")).status, Status.FAIL)
        configured = {".credo.exs": '%{configs: [%{name: "default", strict: true}]}\n', **_ci("mix credo")}
        self.assertEqual(self._run(compiler_warnings, configured).status, Status.PASS)

    def test_warnings_as_errors_in_ci_or_in_mix_exs(self) -> None:
        for command in ("mix compile --warnings-as-errors", "mix test --warnings-as-errors"):
            with self.subTest(command=command):
                self.assertEqual(self._run(warnings_as_errors, _ci(command)).status, Status.PASS)
        option = {
            "mix.exs": "defmodule Shop.MixProject do\n  use Mix.Project\n"
            "  def project, do: [elixirc_options: [warnings_as_errors: true]]\nend\n"
        }
        self.assertEqual(self._run(warnings_as_errors, {**option, **_ci("mix compile")}).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("mix compile")).status, Status.FAIL)

    def test_credo_is_static_analysis_with_or_without_its_configuration(self) -> None:
        self.assertEqual(self._run(static_analysis, _ci("mix credo")), Result.passed("Credo runs"))
        configured = {".credo.exs": "%{configs: []}\n", **_ci("mix do compile, credo --strict")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("Credo (.credo.exs) runs"))
        self.assertEqual(self._run(static_analysis, _ci("mix compile")).status, Status.FAIL)

    def test_dialyzer_type_checks_and_its_optional_warnings_are_strict(self) -> None:
        self.assertEqual(self._run(type_checking, _ci("mix dialyzer")), Result.passed("Dialyzer runs", mock.ANY))
        flags = {
            "mix.exs": "defmodule Shop.MixProject do\n  use Mix.Project\n"
            "  def project, do: [dialyzer: [flags: [:underspecs, :unmatched_returns]]]\nend\n"
        }
        result = self._run(type_checking, {**flags, **_ci("mix dialyzer")})
        self.assertEqual(result.message, "Dialyzer runs; strict mode bonus: Dialyzer (mix.exs)")
        self.assertEqual(self._run(type_checking, _ci("mix test")).status, Status.FAIL)

    def test_sobelow_scans_phoenix_applications(self) -> None:
        self.assertEqual(self._run(security_scanning, _ci("mix sobelow --exit")).status, Status.PASS)
        self.assertEqual(self._run(security_scanning, github_steps("uses: sobelow/action@v1")).status, Status.PASS)
        self.assertEqual(
            self._run(security_scanning, github_steps("uses: github/codeql-action/analyze@v3")).status, Status.WARN
        )

    def test_mix_audit_audits_the_hex_packages(self) -> None:
        for command in ("mix deps.audit", "mix hex.audit"):
            with self.subTest(command=command):
                self.assertEqual(self._run(dependency_audit, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(dependency_audit, _ci("mix deps.get")).status, Status.WARN)

    def test_mix_dependencies_are_locked_by_mix_lock(self) -> None:
        result = self._run(dependency_management, MIX_DEPS)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("mix.lock", " ".join(result.details))
        self.assertEqual(self._run(dependency_management, {**MIX_DEPS, "mix.lock": "%{}\n"}).status, Status.PASS)
        self.assertEqual(self._run(dependency_management, {}).status, Status.PASS)

    def test_a_mix_project_ignores_build_deps_and_crash_dumps(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "_build/\ndeps/\nerl_crash.dump\n"}).status, Status.PASS)
        result = self._run(vcs_ignore, {".gitignore": "_build/\nerl_crash.dump\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("deps/", result.message + " ".join(result.details))
        self.assertEqual(self._run(committed_artifacts, {"deps/jason/mix.exs": ""}).status, Status.FAIL)
        self.assertEqual(
            self._run(committed_artifacts, {"_build/dev/lib/shop/ebin/Elixir.Shop.beam": ""}).status, Status.FAIL
        )

    def test_the_platform_matrix_pairs_elixir_and_otp_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: ELIXIR_OTP_MATRIX})
        self.assertIn(
            "4 Erlang/OTP or Elixir version(s) (Elixir 1.17 / OTP 26, Elixir 1.17 / OTP 27, Elixir 1.18 / OTP 26, "
            "Elixir 1.18 / OTP 27)",
            result.message,
        )
        image = {
            GITHUB_WORKFLOW: "jobs:\n  test:\n    runs-on: ubuntu-latest\n    container: elixir:1.18.3-otp-27\n"
            "    steps:\n      - run: mix test\n"
        }
        self.assertIn(
            "1 Erlang/OTP or Elixir version(s) (Elixir 1.18.3 / OTP 27)", self._run(platform_matrix, image).message
        )


class ErlangTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, REBAR3, selected, files)

    def test_erlfmt_enforces_the_formatting_when_it_checks(self) -> None:
        for command in ("rebar3 fmt --check", "rebar3 fmt -c", "erlfmt --check src/*.erl", "rebar3 do fmt --check, ct"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(code_formatting, _ci(command)), Result.passed("CI enforces the erlfmt style")
                )
        self.assertEqual(self._run(code_formatting, _ci("rebar3 fmt")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("erlfmt -w src/*.erl")).status, Status.FAIL)

    def test_eunit_and_common_test_run_by_rebar3(self) -> None:
        self.assertEqual(self._run(tests_run, {**EUNIT, **_ci("rebar3 eunit")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**SUITE, **_ci("rebar3 as test ct")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**EUNIT, **SUITE, **_ci("rebar3 do eunit, ct")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**EUNIT, **_ci("rebar3 compile")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("rebar3 ct")).status, Status.FAIL)
        no_tests = {"test/shop_tests.erl": "-module(shop_tests).\n", **_ci("rebar3 eunit")}
        self.assertEqual(self._run(tests_run, no_tests).status, Status.FAIL)

    def test_rebar3_cover_reports_lines(self) -> None:
        for command in ("rebar3 cover", "rebar3 do eunit --cover, cover", "rebar3 ct -c", "rebar3 as test cover"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(coverage, _ci(command)),
                    Result.passed(
                        "line coverage is reported with rebar3 cover",
                        "consider failing CI when line coverage falls below a threshold",
                    ),
                )
        self.assertEqual(self._run(coverage, _ci("rebar3 eunit")).status, Status.FAIL)

    def test_the_optional_warnings_and_elvis_are_the_warning_set(self) -> None:
        options = {"rebar.config": "{erl_opts, [debug_info, warn_missing_spec, warn_export_vars]}.\n"}
        result = self._run(compiler_warnings, {**options, **_ci("rebar3 lint")})
        self.assertEqual(result, Result.passed("strict Erlang warnings are enabled: warn_* erl_opts, elvis"))
        self.assertEqual(self._run(compiler_warnings, {**options, **_ci("elvis rock")}).status, Status.PASS)
        self.assertEqual(self._run(compiler_warnings, {**options, **_ci("rebar3 compile")}).status, Status.WARN)
        self.assertEqual(self._run(compiler_warnings, _ci("rebar3 lint")).status, Status.WARN)

    def test_warnings_as_errors_in_erl_opts_or_erlc(self) -> None:
        options = {"rebar.config": "{erl_opts, [debug_info, warnings_as_errors]}.\n"}
        self.assertEqual(self._run(warnings_as_errors, options).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("erlc -Werror -o ebin src/*.erl")).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("rebar3 compile")).status, Status.FAIL)

    def test_elvis_and_xref_are_static_analysis(self) -> None:
        configured = {"elvis.config": "[{elvis, [{config, []}]}].\n", **_ci("rebar3 lint")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("elvis (elvis.config) runs"))
        self.assertEqual(self._run(static_analysis, _ci("elvis rock")), Result.passed("elvis runs"))
        self.assertEqual(self._run(static_analysis, _ci("rebar3 xref")), Result.passed("rebar3 xref runs"))
        self.assertEqual(self._run(static_analysis, _ci("rebar3 dialyzer")).status, Status.FAIL)

    def test_dialyzer_and_eqwalizer_type_check(self) -> None:
        self.assertEqual(self._run(type_checking, _ci("rebar3 dialyzer")).status, Status.PASS)
        warnings = {"rebar.config": "{dialyzer, [{warnings, [unmatched_returns, underspecs]}]}.\n"}
        result = self._run(type_checking, {**warnings, **_ci("rebar3 as test dialyzer")})
        self.assertEqual(result.message, "Dialyzer runs; strict mode bonus: Dialyzer (rebar.config)")
        self.assertEqual(self._run(type_checking, _ci("elp eqwalize-all")), Result.passed("eqWAlizer runs", mock.ANY))

    def test_nothing_scans_erlang(self) -> None:
        self.assertEqual(self._run(security_scanning, _ci("mix sobelow")).status, Status.SKIP)

    def test_rebar3_dependencies_are_locked_by_rebar_lock(self) -> None:
        self.assertEqual(self._run(dependency_management, REBAR_DEPS).status, Status.WARN)
        locked = {**REBAR_DEPS, "rebar.lock": '{"1.2.0",\n[{<<"jsx">>,{pkg,<<"jsx">>,<<"3.1.0">>},0}]}.\n'}
        self.assertEqual(self._run(dependency_management, locked).status, Status.PASS)
        self.assertEqual(self._run(dependency_audit, _ci("osv-scanner -r .")).status, Status.PASS)

    def test_a_rebar3_project_has_no_deps_directory_to_ignore(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "_build/\nerl_crash.dump\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "_build/\n"}).status, Status.WARN)
        self.assertEqual(self._run(committed_artifacts, {"rebar3.crashdump": ""}).status, Status.FAIL)

    def test_the_platform_matrix_counts_otp_versions_alone(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  test:
                    runs-on: ${{ matrix.os }}
                    strategy:
                      matrix:
                        os: [ubuntu-latest, windows-latest]
                        otp: ["26.2", "27.3"]
                    steps:
                      - uses: erlef/setup-beam@v1
                        with:
                          otp-version: ${{ matrix.otp }}
                      - run: rebar3 ct
                """
        }
        self.assertIn(
            "2 Erlang/OTP or Elixir version(s) (OTP 26.2, OTP 27.3)", self._run(platform_matrix, files).message
        )
        image = {
            GITHUB_WORKFLOW: "jobs:\n  test:\n    runs-on: ubuntu-latest\n    container: erlang:27.3\n"
            "    steps:\n      - run: rebar3 ct\n"
        }
        self.assertIn("(OTP 27.3)", self._run(platform_matrix, image).message)
