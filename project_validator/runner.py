"""Selecting and running checks; one misbehaving check never stops the others."""

from collections.abc import Iterable
from dataclasses import dataclass

from project_validator.core import Check, Context, Result, Status


class SelectionError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Report:
    check: Check
    result: Result


def select(available: Iterable[Check], only: Iterable[str] = (), skip: Iterable[str] = ()) -> list[Check]:
    available = list(available)
    only, skip = set(only), set(skip)
    if unknown := sorted((only | skip) - {candidate.name for candidate in available}):
        raise SelectionError(f"unknown check(s): {', '.join(unknown)}")
    return [c for c in available if (not only or c.name in only) and c.name not in skip]


def _skipped(selected: Check, context: Context) -> Result | None:
    if not selected.languages:
        return None
    languages = context.structure.languages
    if selected.applies_to(languages):
        return None
    found, wanted = ", ".join(sorted(languages)), ", ".join(sorted(selected.languages))
    return Result(status=Status.SKIP, message=f"not applicable to {found} (applies to {wanted})")


def run_check(selected: Check, context: Context) -> Result:
    try:
        if skipped := _skipped(selected, context):
            return skipped
        result = selected.run(context)
    except Exception as error:
        return Result(status=Status.ERROR, message=f"check raised {type(error).__name__}: {error}")
    if not isinstance(result, Result):
        return Result(status=Status.ERROR, message=f"check returned {type(result).__name__} instead of a Result")
    return result


def run_checks(selected: Iterable[Check], context: Context) -> list[Report]:
    return [Report(check=c, result=run_check(c, context)) for c in selected]


def succeeded(reports: Iterable[Report], *, strict: bool = False) -> bool:
    failing = {Status.FAIL, Status.ERROR} | ({Status.WARN} if strict else set())
    return all(report.result.status not in failing for report in reports)
