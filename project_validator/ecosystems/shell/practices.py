"""The shells' practices: the lints stand for the compiler warnings a shell does not have. shellcheck fails on any
finding, so running it treats warnings as errors; PSScriptAnalyzer does with `-EnableExit`."""

from __future__ import annotations

import re

from project_validator.ecosystems.shell import POWERSHELL_ONLY, SHELL_ONLY
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always

SHELLCHECK_RUNS = Requirement(name="shellcheck", tools=("shellcheck",))
SHELLCHECK_FAILS = Requirement(name="shellcheck, which fails on any finding", tools=("shellcheck",))
PSSCRIPTANALYZER_RUNS = Requirement(name="PSScriptAnalyzer", tools=("PSScriptAnalyzer",))
PSSCRIPTANALYZER_FAILS = Requirement(
    name="Invoke-ScriptAnalyzer -EnableExit",
    runs=re.compile(r"(?i)\bInvoke-ScriptAnalyzer\b.*\s-EnableExit\b"),
    hints=("-EnableExit", "-enableexit"),
)

SHELL_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=SHELL_ONLY,
    requirements=always(SHELLCHECK_RUNS),
    words=Wording(
        kind="shell lints",
        searched="CI configuration",
        hint="run shellcheck over the scripts in CI (shellcheck scripts/*.sh, or ludeeus/action-shellcheck); "
        ".shellcheckrc holds its settings",
    ),
)
SHELL_WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=SHELL_ONLY,
    requirements=always(SHELLCHECK_FAILS),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration",
        hint="run shellcheck in CI: it fails on any finding",
    ),
)
POWERSHELL_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=POWERSHELL_ONLY,
    requirements=always(PSSCRIPTANALYZER_RUNS),
    words=Wording(
        kind="PowerShell lints",
        searched="CI configuration",
        hint="run Invoke-ScriptAnalyzer -Path . -Recurse in CI; PSScriptAnalyzerSettings.psd1 holds its settings",
    ),
)
POWERSHELL_WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=POWERSHELL_ONLY,
    requirements=always(PSSCRIPTANALYZER_FAILS),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration",
        hint="give Invoke-ScriptAnalyzer -EnableExit, so that a finding fails the job",
    ),
)
