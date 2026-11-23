"""Every CI configuration of the project is in use: one left from a CI the project moved away from misleads its
readers about what is tested (see `project_validator.ci.defunct`)."""

from __future__ import annotations

from project_validator.ci.defunct import Defunct
from project_validator.core import Context, Result, check

REMOVE_HINT = (
    "remove a CI configuration the project no longer runs, or bring it back to life: "
    "one that does not run misleads its readers about what is tested"
)
HISTORY_NOTE = (
    "neither the git history nor the file dates (alike in a fresh or shallow clone) tell when each CI configuration "
    "last changed, so their ages are not compared"
)


@check(
    name="ci-current", description="Every CI configuration is in use, none left from a CI the project moved away from"
)
def ci_current(context: Context) -> Result:
    if not context.ci_files:
        return Result.skipped("no CI configuration")
    found = context.ci_currency
    note = (HISTORY_NOTE,) if found.undated else ()
    reasons = tuple(reason for defunct in found.defunct for reason in (*defunct.certain, *defunct.history))
    if certain := [defunct for defunct in found.defunct if defunct.certain]:
        return Result.failed(
            f"{_count(certain)} {_be(certain, 'is', 'are')} defunct: {_names(certain)}", *reasons, REMOVE_HINT, *note
        )
    if found.defunct:
        unused = list(found.defunct)
        return Result.warned(
            f"{_count(unused)} {_be(unused, 'looks', 'look')} unused: {_names(unused)}", *reasons, REMOVE_HINT
        )
    return Result.passed("no CI configuration is known to be defunct", *note)


def _count(defunct: list[Defunct]) -> str:
    return f"{len(defunct)} CI configuration{'' if len(defunct) == 1 else 's'}"


def _be(defunct: list[Defunct], one: str, more: str) -> str:
    return one if len(defunct) == 1 else more


def _names(defunct: list[Defunct]) -> str:
    return ", ".join(found.provider for found in defunct)
