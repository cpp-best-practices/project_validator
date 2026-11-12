"""Shell and PowerShell: scripts with no build system, recognised by their suffixes (`.sh`, `.bash`, `.zsh`, `.bats`;
`.ps1`, `.psm1`) or, for a script without one, by its shebang, and judged by the tools CI runs on them: bats, shellspec
or shunit2 under kcov, shfmt and shellcheck for the shell; Pester with its code coverage and PSScriptAnalyzer for
PowerShell (`tools.py`, `practices.py`).

A project's helper scripts make Shell one of its languages like any other source does, judged in the units they are
in; `--auxiliary` (by language, `shell`, or by directory, `scripts/`) dials that back to warnings.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem, toolchain_patterns
from project_validator.tools.shell_scripts import SHELLS, interpreter

SHELL = "Shell"
POWERSHELL = "PowerShell"
SHELL_ONLY = frozenset({SHELL})
POWERSHELL_ONLY = frozenset({POWERSHELL})
SHELL_LANGUAGES = SHELL_ONLY | POWERSHELL_ONLY


def shebang_scripts(project: Project) -> frozenset[str]:
    """The languages of the project's scripts without a suffix (`bin/shop`), told by their shebang: a shell's
    (`#!/usr/bin/env bash`) or `pwsh`."""
    found: set[str] = set()
    for path in project.files():
        if PurePosixPath(path).suffix:
            continue
        named = interpreter(project.read_head(path, 160))
        if named in SHELLS:
            found.add(SHELL)
        elif named == "pwsh":
            found.add(POWERSHELL)
    return frozenset(found)


SHELL_ECOSYSTEM = Ecosystem(
    label="Shell",
    languages=SHELL_LANGUAGES,
    source_suffixes={
        ".sh": SHELL,
        ".bash": SHELL,
        ".zsh": SHELL,
        ".bats": SHELL,
        ".ps1": POWERSHELL,
        ".psm1": POWERSHELL,
    },
    # A module manifest describes a module in data, so it is not a program.
    ambiguous_suffixes={".psd1": None},
    detect=shebang_scripts,
    # Shells have no version CI names; a job uses the shell toolchain when it runs a shell or one of its tools.
    toolchain=toolchain_patterns(
        SHELL,
        programs=(*sorted(SHELLS), "shellcheck", "shfmt", "bats", "shellspec", "shunit2", "kcov"),
        actions=("action-shellcheck", "setup-shfmt", "bats-action"),
    ),
    ci_programs=(("pwsh",), ("powershell",), ("Invoke-Pester",), ("Invoke-ScriptAnalyzer",)),
)
