"""The Julia profile's rules, judged by the generic checks in the Julia package and Julia sources layouts."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.julia import JULIA_ECOSYSTEM, julia_code
from tests.support import GITHUB_WORKFLOW, command, github_job, github_steps, make_context, run_as, temp_project

JULIA = frozenset({"Julia"})
TESTS = {"test/runtests.jl": 'using Test\n@testset "Shop" begin\n    @test 1 + 1 == 2\nend\n'}
PKG_TEST = "julia --project -e 'using Pkg; Pkg.test()'"
JULIA_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            version: ["lts", "1", "pre"]
        steps:
          - uses: julia-actions/setup-julia@v3
            with:
              version: ${{ matrix.version }}
          - uses: julia-actions/julia-runtest@v1
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _steps(*steps: dict[str, object]) -> dict[str, str]:
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": list(steps)}}})}


def _action(name: str, **inputs: str) -> dict[str, str]:
    return _steps({"uses": name, "with": inputs} if inputs else {"uses": name})


class RecognitionTests(unittest.TestCase):
    def test_a_project_toml_naming_a_package_is_pkgs(self) -> None:
        with temp_project({"Project.toml": 'name = "Shop"\nuuid = "x"\n', "src/Shop.jl": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (JULIA, frozenset({"Pkg"})))
        with temp_project({"Project.toml": '[deps]\nJSON = "682c06a0-de6a-54ab-a142-c8b1cf79cde6"\n'}) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset({"Pkg"}))
        with temp_project({"Project.toml": "# a settings file of some other tool\nkey = 1\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())

    def test_julia_code_of_a_command(self) -> None:
        self.assertEqual(julia_code(command(PKG_TEST)), "using Pkg; Pkg.test()")
        self.assertEqual(julia_code(command("julia --color=yes -E '1 + 1' --eval 'exit()'")), "1 + 1\nexit()")
        self.assertEqual(julia_code(command("julia --project test/runtests.jl")), "test/runtests.jl")
        self.assertEqual(julia_code(command("juliaup add lts")), "")

    def test_ci_usage(self) -> None:
        for text in (PKG_TEST, "uses: julia-actions/julia-buildpkg@v1", "juliaup add 1.10"):
            with self.subTest(text=text):
                self.assertTrue(JULIA_ECOSYSTEM.used_by(text))
        self.assertFalse(JULIA_ECOSYSTEM.used_by("npm test"))


class JuliaTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, JULIA_ECOSYSTEM)

    def test_pkg_test_runs_the_tests(self) -> None:
        for files in (
            _ci(PKG_TEST),
            _ci("julia --project test/runtests.jl"),
            _action("julia-actions/julia-runtest@v1"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(tests_run, {**TESTS, **files}).status, Status.PASS)
        script = _steps({"run": "using Pkg\nPkg.test(coverage=true)\n", "shell": "julia --color=yes {0}"})
        self.assertEqual(self._run(tests_run, {**TESTS, **script}).status, Status.PASS)
        self.assertEqual(
            self._run(tests_run, {**TESTS, **_ci("julia --project -e 'using Pkg; Pkg.build()'")}).status, Status.WARN
        )
        self.assertEqual(self._run(tests_run, _ci(PKG_TEST)).status, Status.FAIL)

    def test_code_coverage_counts_lines(self) -> None:
        passed = Result.passed("line coverage is reported with julia --code-coverage")
        for files in (
            _ci("julia --code-coverage=user --project -e 'using Pkg; Pkg.test()'"),
            _ci("julia --project -e 'using Pkg; Pkg.test(coverage=true)'"),
            _action("julia-actions/julia-runtest@v1"),
            _action("julia-actions/julia-processcoverage@v1"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(coverage, files), passed)
        self.assertEqual(
            self._run(coverage, _action("julia-actions/julia-runtest@v1", coverage="false")).status, Status.FAIL
        )
        self.assertEqual(self._run(coverage, _ci(PKG_TEST)).status, Status.FAIL)

    def test_aqua_in_the_tests_is_the_warning_set(self) -> None:
        aqua = {"test/runtests.jl": "using Aqua\nAqua.test_all(Shop)\n"}
        self.assertEqual(
            self._run(compiler_warnings, aqua), Result.passed("strict Aqua.jl checks are enabled: Aqua.test_all")
        )
        some = {"test/quality.jl": "Aqua.test_ambiguities(Shop)\n"}
        self.assertEqual(self._run(compiler_warnings, some).status, Status.PASS)
        self.assertEqual(self._run(compiler_warnings, TESTS).status, Status.FAIL)

    def test_deprecations_are_errors_with_depwarn(self) -> None:
        passed = Result.passed("warnings are treated as errors with --depwarn=error")
        self.assertEqual(self._run(warnings_as_errors, _ci("julia --depwarn=error -e 'using Pkg; Pkg.test()'")), passed)
        self.assertEqual(
            self._run(warnings_as_errors, _action("julia-actions/julia-runtest@v1", depwarn="error")), passed
        )
        self.assertEqual(self._run(warnings_as_errors, _action("julia-actions/julia-runtest@v1")).status, Status.FAIL)

    def test_jet_type_checks_when_the_tests_call_it(self) -> None:
        jet = {"test/runtests.jl": "using JET\nJET.test_package(Shop; target_defined_modules = true)\n"}
        self.assertEqual(self._run(type_checking, {**jet, **_ci(PKG_TEST)}).message, "JET.jl runs")
        self.assertEqual(self._run(type_checking, jet).status, Status.FAIL)
        self.assertEqual(self._run(type_checking, {**TESTS, **_ci(PKG_TEST)}).status, Status.FAIL)

    def test_juliaformatter_checks_when_the_script_fails_on_changes(self) -> None:
        checking = "julia -e 'using JuliaFormatter; format(\".\") || exit(1)'"
        self.assertEqual(
            self._run(code_formatting, _ci(checking)), Result.passed("CI enforces the JuliaFormatter style")
        )
        self.assertEqual(self._run(code_formatting, _action("julia-actions/julia-format@v4")).status, Status.PASS)
        styled = {".JuliaFormatter.toml": 'style = "blue"\n', **_ci(checking)}
        self.assertEqual(
            self._run(code_formatting, styled).message, ".JuliaFormatter.toml is defined and CI runs JuliaFormatter"
        )
        rewriting = _ci("julia -e 'using JuliaFormatter; format(\".\")'")
        self.assertEqual(self._run(code_formatting, rewriting).status, Status.FAIL)
        enforced = _ci("julia -e 'using JuliaFormatter; format(\".\")'", "git diff --exit-code")
        self.assertEqual(self._run(code_formatting, enforced).status, Status.PASS)

    def test_runic(self) -> None:
        self.assertEqual(
            self._run(code_formatting, _ci("runic --check .")), Result.passed("CI enforces the Runic style")
        )
        self.assertEqual(self._run(code_formatting, _ci("julia -m Runic --check .")).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _action("fredrikekre/runic-action@v1")).status, Status.PASS)
        self.assertEqual(
            self._run(code_formatting, _action("fredrikekre/runic-action@v1", format_files="true")).status, Status.FAIL
        )
        self.assertEqual(self._run(code_formatting, _ci("runic --inplace .")).status, Status.FAIL)

    def test_semgrep_reads_julia_and_codeql_does_not(self) -> None:
        semgrep = self._run(security_scanning, _ci("pipx run semgrep scan --config auto --error ."))
        self.assertEqual(semgrep.status, Status.PASS)
        self.assertEqual(
            self._run(security_scanning, github_steps("uses: github/codeql-action/analyze@v3")).status, Status.WARN
        )

    def test_coverage_and_allocation_files_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.jl.cov\n*.jl.*.cov\n*.jl.mem\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.cov\n*.mem\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "*.jl.cov\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_julia_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: JULIA_MATRIX})
        self.assertIn("3 Julia version(s) (1, lts, pre)", result.message)
        for files, version in (
            (_ci("docker run julia:1.10 julia -e 'using Pkg; Pkg.test()'"), "1.10"),
            (_ci("juliaup add 1.11", PKG_TEST), "1.11"),
            (_ci(PKG_TEST), "default"),
        ):
            with self.subTest(files=files):
                self.assertIn(f"1 Julia version(s) ({version})", self._run(platform_matrix, files).message)
        # An input called `version` names a Julia version under setup-julia only.
        other = _steps({"uses": "fortran-lang/setup-fortran@v1", "with": {"version": "14"}}, {"run": PKG_TEST})
        self.assertIn("1 Julia version(s) (default)", self._run(platform_matrix, other).message)
