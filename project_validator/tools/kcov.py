"""kcov: the line coverage of whatever runs under it, without instrumentation (`kcov <report directory> <command>`): a
shell script, through bash's debug trap, or a compiled test binary, through its debug information. Shared by the
languages whose tests run under it (Shell, Zig); each profile says how its tests get there."""

from __future__ import annotations

from collections.abc import Callable

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import program
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.expansion import launcher
from project_validator.facts.tools import Run, Tool


def kcov_tool(languages: frozenset[str], *, how: str, wrapped: Callable[[Command], bool] | None = None) -> Tool:
    """kcov for `languages`: `how` to run their tests under it, and `wrapped`, the language's own commands that run
    kcov in turn (`zig test --test-cmd kcov`, `shellspec --kcov`). kcov reports lines; it gates nothing."""

    def measures(command: Command, _facts: Facts) -> Run | None:
        runs = program(resolved(command)) == "kcov" or (wrapped is not None and wrapped(command))
        return reported(Granularity.LINE) if runs else None

    return coverage_tool(name="kcov", languages=languages, can={Granularity.LINE: how}, measures=measures)


# kcov runs the command after its options and the report directory (`kcov --include-path=src coverage bats tests`),
# so what runs under it is a command of its own.
KCOV_LAUNCHER = launcher("kcov", (("kcov",),), positionals=1)
