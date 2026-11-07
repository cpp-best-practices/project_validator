"""Shell scripts of the project that CI runs (`ci/lint.sh`, `bash scripts/check.sh`): the commands they run in turn.

A script runs where the command that runs it does; its arguments (`$1`) are not known. Shell functions it defines
are not followed: their bodies are split like any other lines.
"""

from pathlib import PurePosixPath

from project_validator.core import Context
from project_validator.facts import Command, Origin, resolved
from project_validator.facts.arguments import positional, program
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined

_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Shell options that take a value (`bash -o pipefail script.sh`).
_SHELL_VALUES = frozenset({"-o", "+o", "-O", "+O"})
_SHEBANG = ("#!/bin/sh", "#!/bin/bash", "#!/usr/bin/env bash", "#!/usr/bin/env sh", "#!/usr/bin/env zsh")


def _script(command: Command) -> str | None:
    """The script file a command runs: `sh script.sh` (not `sh -c '…'`), `./script.sh` run directly, or a script
    the shell sources (`. ci/env.sh`, `source ci/env.sh`)."""
    argv = resolved(command)
    if argv[:1] in ((".",), ("source",)):
        return argv[1] if len(argv) > 1 else None
    if program(argv) in _SHELLS:
        words, _ = positional(argv, _SHELL_VALUES)
        return None if "-c" in argv[1:] or not words else words[0]
    return argv[0] if argv and ("/" in argv[0] or argv[0].endswith(".sh")) else None


def _is_shell_script(text: str, path: str) -> bool:
    return path.endswith(".sh") or text.startswith(_SHEBANG)


def _shell_script(command: Command, context: Context) -> list[Expansion] | None:
    path = _script(command)
    if path is None or path.startswith(("/", "$", "~")):
        return None
    found = joined(command.directory, path.removeprefix("./"))
    if not context.project.exists(found) or not _is_shell_script(text := context.project.read_text(found), found):
        return None
    return [Script(text=text, origin=Origin(path=str(PurePosixPath(found))))]


SHELL_SCRIPTS = CommandExpander(name="shell scripts", expand=_shell_script)
