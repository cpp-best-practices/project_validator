"""The Shell profile's rules, judged by the generic checks in the shell scripts and PowerShell module layouts."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.shell import SHELL_ECOSYSTEM
from project_validator.ecosystems.shell.tools import PESTER_SETTINGS
from project_validator.facts import Setting
from tests.support import github_job, github_steps, make_context, run_in_layout, temp_project, uses

SCRIPTS, MODULE = "Shell scripts", "PowerShell module"
BATS = {"tests/shop.bats": '@test "sums the prices" {\n  run total 1 2\n  [ "$output" = "3" ]\n}\n'}
SPEC = {"spec/shop_spec.sh": "Describe 'total'\n  It 'sums the prices'\n    When call total 1 2\n  End\nEnd\n"}
SHUNIT2 = {"tests/shop_test.sh": 'testTotal() {\n  assertEquals 3 "$(total 1 2)"\n}\n. shunit2\n'}
PESTER = {
    "tests/Shop.Tests.ps1": "Describe 'Get-Total' {\n    It 'sums the prices' {\n        1 | Should -Be 1\n    }\n}\n"
}
PESTER_CONFIGURED = "$configuration = New-PesterConfiguration\n$configuration.CodeCoverage.Enabled = $true\n"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _windows(*steps: str) -> dict[str, str]:
    """A Windows job: its steps run in PowerShell."""
    return github_job("windows-latest", *steps)


def _coverage_setting(text: str) -> object:
    found = [setting for setting in PESTER_SETTINGS.read("build.ps1", text) if isinstance(setting, Setting)]
    return found[0].value if found else None


class RecognitionTests(unittest.TestCase):
    def test_scripts_modules_and_the_shebang_of_a_script_without_a_suffix(self) -> None:
        cases: tuple[tuple[dict[str, str], set[str]], ...] = (
            ({"src/shop.sh": "", "src/Shop.psm1": "", "Shop.psd1": "@{}\n"}, {"Shell", "PowerShell"}),
            ({"bin/shop": "#!/usr/bin/env bash\necho hi\n"}, {"Shell"}),
            ({"bin/shop": "#!/bin/sh\necho hi\n"}, {"Shell"}),
            ({"bin/shop": "#!/usr/bin/env pwsh\nWrite-Host hi\n"}, {"PowerShell"}),
            ({"bin/shop": "#!/usr/bin/env python3\nprint('hi')\n"}, set()),
            ({"tests/shop.bats": '@test "x" { true; }\n'}, {"Shell"}),
        )
        for files, languages in cases:
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual(structure.languages, frozenset(languages))
                self.assertEqual(structure.unrecognised_suffixes, ())

    def test_ci_usage(self) -> None:
        used = (
            "shellcheck src/shop.sh",
            "bats tests",
            "kcov --include-path=src coverage bats tests",
            "bash scripts/check.sh",
            "uses: ludeeus/action-shellcheck@v2",
            "Invoke-Pester -Path tests",
            "pwsh -File build.ps1",
        )
        for text in used:
            with self.subTest(text=text):
                self.assertTrue(uses(SHELL_ECOSYSTEM, text))
        for text in ("npm test", "cargo test", "make check"):
            with self.subTest(text=text):
                self.assertFalse(uses(SHELL_ECOSYSTEM, text))


class ShellTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, SCRIPTS, selected, files)

    def test_bats_shellspec_and_shunit2_run_their_tests(self) -> None:
        cases = (
            ({**BATS, **_ci("bats tests")}, Status.PASS),
            ({**SPEC, **_ci("shellspec")}, Status.PASS),
            ({**SHUNIT2, **_ci("./tests/shop_test.sh")}, Status.PASS),
            ({**SHUNIT2, **_ci("bash tests/shop_test.sh")}, Status.PASS),
            ({**SHUNIT2, **_ci("shunit2 tests/shop_test.sh")}, Status.PASS),
            ({**BATS, **_ci("shellcheck src/shop.sh")}, Status.WARN),
            (_ci("bats tests"), Status.FAIL),
        )
        for files, status in cases:
            with self.subTest(files=files):
                self.assertEqual(self._run(tests_run, files).status, status)

    def test_kcov_reports_lines_and_runs_the_tests_under_it(self) -> None:
        for files in (_ci("kcov --include-path=src coverage bats tests"), _ci("shellspec --kcov")):
            with self.subTest(files=files):
                result = self._run(coverage, files)
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("line coverage is reported with kcov", result.message)
        self.assertEqual(self._run(tests_run, {**BATS, **_ci("kcov coverage bats tests")}).status, Status.PASS)
        self.assertEqual(self._run(coverage, _ci("bats tests")).status, Status.FAIL)

    def test_shfmt_checks_with_diff_or_list_and_reads_editorconfig(self) -> None:
        for line in ("shfmt -d .", "shfmt -l src", "shfmt --diff src bin", "shfmt -i 2 -d ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)), Result.passed("CI enforces the shfmt style"))
        styled = {".editorconfig": "[*.sh]\nindent_style = space\n", **_ci("shfmt -d .")}
        self.assertEqual(self._run(code_formatting, styled).message, ".editorconfig is defined and CI runs shfmt")
        for line in ("shfmt -w .", "shfmt ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)

    def test_shellcheck_is_the_lint_the_errors_and_the_analyzer(self) -> None:
        for files in (_ci("shellcheck src/*.sh"), github_steps("uses: ludeeus/action-shellcheck@v2")):
            with self.subTest(files=files):
                self.assertEqual(
                    self._run(compiler_warnings, files), Result.passed("strict shell lints are enabled: shellcheck")
                )
                self.assertEqual(
                    self._run(warnings_as_errors, files),
                    Result.passed("warnings are treated as errors with shellcheck, which fails on any finding"),
                )
                self.assertEqual(self._run(static_analysis, files), Result.passed("shellcheck runs"))
        configured = {".shellcheckrc": "shell=bash\n", **_ci("shellcheck src/shop.sh")}
        self.assertEqual(self._run(static_analysis, configured), Result.passed("shellcheck (.shellcheckrc) runs"))
        for selected in (compiler_warnings, warnings_as_errors, static_analysis):
            with self.subTest(check=selected.name):
                self.assertEqual(self._run(selected, _ci("bats tests")).status, Status.FAIL)


class PowerShellTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, MODULE, selected, files)

    def test_pester_runs_the_tests(self) -> None:
        for line in ("Invoke-Pester -Path tests", "invoke-pester", "Invoke-Pester -CI"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**PESTER, **_windows(line)}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**PESTER, **_windows("Install-Module Pester")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _windows("Invoke-Pester")).status, Status.FAIL)

    def test_pester_counts_statements_when_code_coverage_is_on(self) -> None:
        configured = {"build.ps1": f"{PESTER_CONFIGURED}Invoke-Pester -Configuration $configuration\n"}
        cases = (
            _windows("Invoke-Pester -Path tests -CodeCoverage src/Shop.psm1"),
            _windows("Invoke-Pester -CI"),
            {**configured, **_windows("Invoke-Pester -Configuration $configuration")},
        )
        for files in cases:
            with self.subTest(files=files):
                result = self._run(coverage, files)
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("statement coverage is reported with Pester", result.message)
        self.assertEqual(self._run(coverage, _windows("Invoke-Pester -Path tests")).status, Status.FAIL)

    def test_the_code_coverage_setting_is_read_from_scripts(self) -> None:
        self.assertIs(_coverage_setting(PESTER_CONFIGURED), True)
        self.assertIs(
            _coverage_setting("$c = New-PesterConfiguration @{ CodeCoverage = @{ Enabled = $true } }\n"), True
        )
        self.assertIsNone(_coverage_setting("$configuration = New-PesterConfiguration\nInvoke-Pester\n"))

    def test_psscriptanalyzer_is_the_lint_and_the_analyzer_and_enableexit_makes_findings_errors(self) -> None:
        for files in (
            _windows("Invoke-ScriptAnalyzer -Path . -Recurse"),
            github_steps("uses: microsoft/psscriptanalyzer-action@v1.1"),
        ):
            with self.subTest(files=files):
                self.assertEqual(
                    self._run(compiler_warnings, files),
                    Result.passed("strict PowerShell lints are enabled: PSScriptAnalyzer"),
                )
                self.assertEqual(self._run(static_analysis, files), Result.passed("PSScriptAnalyzer runs"))
                self.assertEqual(self._run(warnings_as_errors, files).status, Status.FAIL)
        configured = {"PSScriptAnalyzerSettings.psd1": "@{}\n", **_windows("Invoke-ScriptAnalyzer -Path . -Recurse")}
        self.assertEqual(
            self._run(static_analysis, configured),
            Result.passed("PSScriptAnalyzer (PSScriptAnalyzerSettings.psd1) runs"),
        )
        strict = _windows("Invoke-ScriptAnalyzer -Path . -Recurse -EnableExit")
        self.assertEqual(
            self._run(warnings_as_errors, strict),
            Result.passed("warnings are treated as errors with Invoke-ScriptAnalyzer -EnableExit"),
        )
        for selected in (compiler_warnings, static_analysis):
            with self.subTest(check=selected.name):
                self.assertEqual(self._run(selected, _windows("Invoke-Pester")).status, Status.FAIL)
