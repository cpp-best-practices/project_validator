"""Whether a command's failure fails the script it is in, or the script throws its exit status away (upstream #334).

A shell keeps going after a failing command unless errexit (`set -e`) is on, and even then it ignores a failure that
a condition tests (`if A`), that a `||` fallback answers, or that comes before `&&`; a pipeline's status is its last
command's unless pipefail is on. A command whose status is thrown away runs, but cannot fail CI: it is advisory (see
`Command.advisory`), with the reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from project_validator.facts.shell import ShellCommand


@dataclass(frozen=True, slots=True, kw_only=True)
class Shell:
    """How a shell treats a failing command: errexit (`-e`) stops the script at it; pipefail makes a pipeline fail
    when any of its commands does, not only its last."""

    errexit: bool = False
    pipefail: bool = False


# `sh -c`: make recipe lines, package scripts.
POSIX = Shell()
# GitHub's default shell on Linux and macOS, `bash -e {0}`, and its `sh`, `sh -e {0}`.
ERREXIT = Shell(errexit=True)
# GitHub's `shell: bash`, `bash --noprofile --norc -eo pipefail {0}`, and GitLab Runner's bash, `set -eo pipefail`.
STRICT = Shell(errexit=True, pipefail=True)

_SHELLS = frozenset({"sh", "bash", "dash", "ksh", "zsh"})
_OPTIONS = {"e": "errexit"}


def shell_of(command_line: str) -> Shell | None:
    """The options a shell's command line sets (`bash -eo pipefail {0}`), up to its first word that is not an option;
    None for a program that is not a POSIX shell."""
    words = command_line.split()
    if not words or PurePosixPath(words[0]).name not in _SHELLS:
        return None
    return set_options(POSIX, words[1:])


def set_options(shell: Shell, words: Sequence[str]) -> Shell:
    """`shell` after the options `words` set or unset, as `set` and a shell's command line have them (`-eu`, `+e`,
    `-o pipefail`, `-euo pipefail`); long options (`--norc`) are passed over, and a word that is no option ends them."""
    rest = iter(words)
    for word in rest:
        if word == "--" or len(word) < 2 or word[0] not in "-+":
            break
        if word.startswith("--"):
            continue
        on = word[0] == "-"
        for letter in word[1:]:
            name = next(rest, "") if letter == "o" else _OPTIONS.get(letter, "")
            if name in ("errexit", "pipefail"):
                shell = replace(shell, **{name: on})
    return shell


def masked(commands: Sequence[ShellCommand], shell: Shell, *, followed: bool = False) -> list[str]:
    """For each of a script's `commands`, in order, why its failure cannot fail the script, or "" when it can; the
    script runs in `shell`, whose options its `set` commands change as it goes (a `set` itself is never reported:
    it is no step whose failure matters). `followed`: more of the script comes after these commands (a GitLab job's
    next script line), so none of them ends it."""
    last = -1 if followed else max((index for index, command in enumerate(commands) if not command.nested), default=-1)
    reasons = []
    for index, command in enumerate(commands):
        reasons.append("" if command.nested or command.argv[0] == "set" else _reason(commands, index, shell, last))
        shell = after((command,), shell)
    return reasons


def after(commands: Sequence[ShellCommand], shell: Shell) -> Shell:
    """`shell` once `commands` have run: as their `set` commands leave its options."""
    for command in commands:
        if command.argv[0] == "set" and not command.nested:
            shell = set_options(shell, command.argv[1:])
    return shell


_CONDITIONS = {
    "if": "an if condition",
    "elif": "an elif condition",
    "while": "a while condition",
    "until": "an until condition",
    "!": "negated by !",
}
_PIPES = frozenset({"|", "|&"})
_JOINS = frozenset({"&&", "||", *_PIPES})


def _end(commands: Sequence[ShellCommand], index: int, joined: frozenset[str]) -> int:
    """The last command of what `commands[index]` begins, where `joined` operators go on to the next command."""
    while commands[index].operator in joined and index + 1 < len(commands) and not commands[index + 1].nested:
        index += 1
    return index


def _reason(commands: Sequence[ShellCommand], index: int, shell: Shell, last: int) -> str:
    command = commands[index]
    pipeline, listed = _end(commands, index, _PIPES), _end(commands, index, _JOINS)
    if command.condition:
        return _CONDITIONS[command.condition]
    if commands[listed].operator == "&":
        return "run in the background"
    if command.operator in _PIPES and not shell.pipefail and not commands[pipeline].checked:
        return f"piped into {commands[index + 1].argv[0]} without pipefail"
    if fallback := commands[pipeline].fallback:
        return f"|| {fallback}"
    if listed == last or commands[listed].checked or commands[pipeline].operator == "||":
        return ""
    if not shell.errexit:
        return "followed by other commands without set -e"
    return "before && in the middle of the script" if commands[pipeline].operator == "&&" else ""


__all__ = ["ERREXIT", "POSIX", "STRICT", "Shell", "after", "masked", "set_options", "shell_of"]
