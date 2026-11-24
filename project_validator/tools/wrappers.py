"""Programs that run the command that follows them (`sudo make`, `exec bats test`, `emcmake cmake`, `xvfb-run npm test`,
`timeout 5m make check`, `find … | xargs clang-format`), shared by every language: each is a launcher (see
`project_validator.facts.expansion.launcher`)."""

from __future__ import annotations

from collections.abc import Mapping

from project_validator.facts.expansion import Action, launcher
from project_validator.facts.shell import ShellCommand, split_script

WRAPPERS = launcher(
    "wrappers",
    (
        *((name,) for name in ("sudo", "time", "nice", "env", "nohup", "xvfb-run", "catchsegv", "exec")),
        *((name,) for name in ("emcmake", "emmake", "emconfigure", "scan-build", "ccache", "sccache")),
    ),
    with_values=frozenset({"-u", "--user", "-g", "--group", "-n", "--adjustment"}),
)
# xargs runs its command with the arguments it reads appended; they are not known.
XARGS = launcher(
    "xargs",
    (("xargs",),),
    with_values=frozenset(
        {"-n", "-P", "-I", "-L", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter", "--arg-file"}
    ),
)
# timeout runs its command after a duration and its options (`timeout --signal=INT -k 2m 30m mutmut run`).
TIMEOUT = launcher(
    "timeout", (("timeout",),), with_values=frozenset({"-s", "--signal", "-k", "--kill-after"}), positionals=1
)


def _run_input(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """The commands of an action's `run` input (a command line, or several)."""
    return tuple(found.argv for found in split_script(inputs.get("run", "")) if isinstance(found, ShellCommand))


# coactions/setup-xvfb runs its `run` input under a virtual display.
XVFB_ACTION = Action(name="coactions/setup-xvfb", runs=_run_input)
# vmactions' virtual machines run their `run` input in the system they boot (tokio's FreeBSD jobs).
VM_ACTIONS = tuple(
    Action(name=f"vmactions/{system}-vm", runs=_run_input)
    for system in ("freebsd", "openbsd", "netbsd", "dragonflybsd", "solaris", "omnios")
)
