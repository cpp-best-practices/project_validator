"""Selecting and running checks; one misbehaving check never stops the others."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, replace

from project_validator.ci.local_checks import ENTRY_LEVEL
from project_validator.core import Check, Context, ExtractionError, Progress, Result, Status


class SelectionError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Report:
    check: Check
    result: Result


def _names_of(candidate: Check) -> set[str]:
    return {candidate.name, *candidate.aliases}


def select(available: Iterable[Check], only: Iterable[str] = (), skip: Iterable[str] = ()) -> list[Check]:
    """The checks named by `only` (every one if empty), minus those named by `skip`; former names count too."""
    available = list(available)
    only, skip = set(only), set(skip)
    if unknown := sorted((only | skip) - set().union(*map(_names_of, available))):
        raise SelectionError(f"unknown check(s): {', '.join(unknown)}")
    return [c for c in available if (not only or _names_of(c) & only) and not _names_of(c) & skip]


def _skipped(selected: Check, context: Context) -> Result | None:
    if not selected.languages:
        return None
    structure = context.structure
    if selected.applies_to(structure.languages_and_formats):
        return None
    # Only the project's own languages are named (not its formats: every project has data files), so that adding a
    # language changes no other project's results; `--list` shows what each check applies to.
    found = ", ".join(sorted(structure.languages)) or "a project of no recognised language"
    return Result.skipped(f"not applicable to {found}")


def _entry_level(result: Result) -> Result:
    """A CI-only check's result when the pipeline is the local checks: a failure warns, saying why (upstream #384)."""
    if result.status is not Status.FAIL:
        return result
    places = tuple(replace(place, result=_entry_level(place.result)) for place in result.places)
    return replace(result, status=Status.WARN, details=(*result.details, ENTRY_LEVEL), places=places)


def run_check(selected: Check, context: Context) -> Result:
    """The check's result; an error when the check raises, or when the facts it needs could not be extracted (said
    the same way by every check that needs them: the one cause is `Context.extraction_error`)."""
    try:
        if skipped := _skipped(selected, context):
            return skipped
        result = selected.run(context)
    except ExtractionError as error:
        return Result(status=Status.ERROR, message=f"not judged: {error}")
    except Exception as error:  # noqa: BLE001 - any failure inside a check is reported, never propagated
        return Result(status=Status.ERROR, message=f"check raised {type(error).__name__}: {error}")
    if not isinstance(result, Result):
        return Result(status=Status.ERROR, message=f"check returned {type(result).__name__} instead of a Result")
    return _entry_level(result) if selected.ci_only and context.local_pipeline else result


def run_checks(selected: Iterable[Check], context: Context) -> list[Report]:
    """Each check's report, in order; each check's start and end are told to the context's observers."""
    selected = list(selected)
    reports = []
    for index, chosen in enumerate(selected, 1):
        context.notify(Progress(kind="check", name=chosen.name, done=False, index=index, total=len(selected)))
        started = time.perf_counter()
        reports.append(Report(check=chosen, result=run_check(chosen, context)))
        seconds = time.perf_counter() - started
        context.notify(
            Progress(kind="check", name=chosen.name, done=True, seconds=seconds, index=index, total=len(selected))
        )
    return reports


def succeeded(reports: Iterable[Report], *, strict: bool = False) -> bool:
    failing = {Status.FAIL, Status.ERROR} | ({Status.WARN} if strict else set())
    return all(report.result.status not in failing for report in reports)
