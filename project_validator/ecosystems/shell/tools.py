"""The shells' tools: the test runners (bats, shellspec, shunit2; Pester), kcov and Pester's code coverage, shfmt,
shellcheck and PSScriptAnalyzer. A PowerShell cmdlet is matched without regard to case, as PowerShell reads it."""

from __future__ import annotations

import re
from collections.abc import Iterator

from project_validator.ecosystems.shell import POWERSHELL_ONLY, SHELL_ONLY
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, program, starts_with
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.settings import SettingsReader, file_reader, settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, combined, defined_by, starts, when
from project_validator.tools.editorconfig import EDITORCONFIG
from project_validator.tools.kcov import kcov_tool
from project_validator.tools.shell_scripts import SHELLS

# --- Tests and coverage ---------------------------------------------------------------------------------------------

BATS_TESTS = TestFiles(
    name="bats tests (*.bats)",
    languages=SHELL_ONLY,
    path=re.compile(r"\.bats$"),
    contains=re.compile(r"^\s*@test\b", re.MULTILINE),
)
SHELLSPEC_TESTS = TestFiles(
    name="shellspec specs (spec/*_spec.sh)",
    languages=SHELL_ONLY,
    path=re.compile(r"(?:^|/)spec/.+_spec\.sh$"),
    contains=re.compile(r"^\s*(?:Describe|Context|It|Example|Specify)\b", re.MULTILINE),
)
SHUNIT2_TESTS = TestFiles(
    name="shunit2 tests (*_test.sh)",
    languages=SHELL_ONLY,
    path=re.compile(r"_test\.sh$"),
    contains=re.compile(r"\bshunit2\b"),
)
PESTER_TESTS = TestFiles(
    name="Pester tests (*.Tests.ps1)",
    languages=POWERSHELL_ONLY,
    path=re.compile(r"\.Tests\.ps1$"),
    contains=re.compile(r"^\s*(?:Describe|It)\b", re.MULTILINE),
)

BATS = test_runner(
    name="bats",
    languages=SHELL_ONLY,
    how="bats tests",
    runs=when(starts(("bats",)), tested),
    tests=tests_of(BATS_TESTS.name),
)
SHELLSPEC = test_runner(
    name="shellspec",
    languages=SHELL_ONLY,
    how="shellspec",
    runs=when(starts(("shellspec",)), tested),
    tests=tests_of(SHELLSPEC_TESTS.name),
)


def _runs_shunit2(command: Command, _facts: Facts) -> Run | None:
    """shunit2 run over a test script, or a `*_test.sh` script (which sources shunit2) run directly or with a shell."""
    argv = resolved(command)
    if program(argv) == "shunit2":
        return tested()
    script = argv[1] if program(argv) in SHELLS and len(argv) > 1 else argv[0] if argv else ""
    return tested() if script.endswith("_test.sh") else None


SHUNIT2 = test_runner(
    name="shunit2",
    languages=SHELL_ONLY,
    how="./tests/shop_test.sh (a script that sources shunit2)",
    runs=_runs_shunit2,
    tests=tests_of(SHUNIT2_TESTS.name),
)


def _shellspec_kcov(command: Command) -> bool:
    """shellspec runs its specs under kcov with `--kcov`."""
    argv = resolved(command)
    return starts_with(argv, ("shellspec",)) is not None and has_option(argv, "--kcov")


KCOV = kcov_tool(SHELL_ONLY, how="kcov <report directory> bats tests (or shellspec --kcov)", wrapped=_shellspec_kcov)

PESTER_NAME = "Pester"
# `$configuration.CodeCoverage.Enabled = $true`, or the hashtable `New-PesterConfiguration` takes.
_COVERAGE_ENABLED = re.compile(
    r"CodeCoverage\.Enabled\s*=\s*\$true|CodeCoverage\s*=\s*@\{[^}]*\bEnabled\s*=\s*\$true", re.IGNORECASE
)


def _read_pester(path: str, text: str) -> Iterator[Setting]:
    """Whether a script or data file turns Pester's code coverage on; heuristic, as the script is not run."""
    if _COVERAGE_ENABLED.search(text):
        yield from settings(PESTER_NAME, path, (("CodeCoverage.Enabled", True),), heuristic=True)


PESTER_SETTINGS = SettingsReader(name=PESTER_NAME, files=("*.ps1", "*.psd1"), read=_read_pester)


def _cmdlet(argv: tuple[str, ...], name: str) -> bool:
    return program(argv).lower() == name


def _pester_tests(command: Command, _facts: Facts) -> Run | None:
    return tested() if _cmdlet(resolved(command), "invoke-pester") else None


def _pester_coverage(command: Command, facts: Facts) -> Run | None:
    """Pester counts the commands run: with `-CodeCoverage <scripts>` (or `-CI`, which turns it on), or when the
    configuration a script builds enables it."""
    argv = resolved(command)
    if not _cmdlet(argv, "invoke-pester"):
        return None
    if any(word.lower() in ("-ci",) or word.lower().startswith("-codecoverage") for word in argv[1:]):
        return reported(Granularity.STATEMENT)
    setting = facts.setting(PESTER_NAME, "CodeCoverage.Enabled")
    if setting is None or not setting.value:
        return None
    return reported(Granularity.STATEMENT, read=(setting,), heuristic=True)


PESTER = combined(
    test_runner(
        name=PESTER_NAME,
        languages=POWERSHELL_ONLY,
        how="Invoke-Pester -Path tests",
        runs=_pester_tests,
        tests=tests_of(PESTER_TESTS.name),
    ),
    coverage_tool(
        name=PESTER_NAME,
        languages=POWERSHELL_ONLY,
        can={
            Granularity.STATEMENT: "Invoke-Pester -CodeCoverage <scripts> (or -CI, or CodeCoverage.Enabled = $true in "
            "its configuration)"
        },
        measures=_pester_coverage,
        reads=(PESTER_NAME,),
    ),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# shfmt has a default style and reads the project's from .editorconfig; `-d` (or `-l`) fails on a file it would change.
SHFMT = format_tool(
    name="shfmt",
    languages=SHELL_ONLY,
    can={Enforcement.CHECK: "shfmt -d .", Enforcement.APPLY: "shfmt -w ."},
    formats=flagged(("shfmt",), checks=("-d", "--diff", "-l", "--list"), applies=("-w", "--write")),
    style=defined_by(files=(EDITORCONFIG.name,)),
)


# --- Lints ----------------------------------------------------------------------------------------------------------

SHELLCHECK_SETTINGS = file_reader("shellcheck", (".shellcheckrc", "shellcheckrc"))
SHELLCHECK = analyzer(
    name="shellcheck",
    languages=SHELL_ONLY,
    how="shellcheck <scripts> (or ludeeus/action-shellcheck)",
    analyses=when(starts(("shellcheck",)), analysed),
    rules=defined_by(files=(SHELLCHECK_SETTINGS.name,)),
)
SHELLCHECK_ACTION = Action(name="ludeeus/action-shellcheck", runs=lambda _inputs: (("shellcheck",),))
REVIEWDOG_SHELLCHECK_ACTION = Action(name="reviewdog/action-shellcheck", runs=lambda _inputs: (("shellcheck",),))

PSSCRIPTANALYZER_SETTINGS = file_reader("PSScriptAnalyzer", ("PSScriptAnalyzerSettings.psd1",))
PSSCRIPTANALYZER = analyzer(
    name="PSScriptAnalyzer",
    languages=POWERSHELL_ONLY,
    how="Invoke-ScriptAnalyzer -Path . -Recurse -EnableExit",
    analyses=lambda command, _facts: analysed() if _cmdlet(resolved(command), "invoke-scriptanalyzer") else None,
    rules=defined_by(files=(PSSCRIPTANALYZER_SETTINGS.name,)),
)
PSSCRIPTANALYZER_ACTION = Action(
    name="microsoft/psscriptanalyzer-action", runs=lambda _inputs: (("Invoke-ScriptAnalyzer",),)
)
