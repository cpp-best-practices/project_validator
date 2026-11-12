"""The coverage policy: branch coverage is required (or the finest a known tool measures), path coverage a bonus.
Measuring the required coverage passes; reporting it where it can be seen, and failing CI under a threshold, are
suggested when nothing does."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.facts.coverage import Granularity, Rung
from project_validator.policy import unknown
from project_validator.questions import Answer
from project_validator.questions.coverage import CoverageAnswer, GranularityAnswer


def required_coverage(answer: CoverageAnswer) -> Granularity | None:
    """Branch coverage, or the finest a known tool measures for the language when none measures branches; None when
    no known tool measures the language's coverage at all."""
    possible = [found for found in answer.possible() if found.rank <= Granularity.BRANCH.rank]
    return possible[-1] if possible else None


def _missing(answer: CoverageAnswer, required: Granularity, *, allow_unknown: bool) -> Result:
    coarser = (
        _reached(granularity, answer[granularity])
        for granularity in answer.possible()
        if granularity.rank < required.rank and answer[granularity].answer is Answer.YES
    )
    known = f"known to measure {required} coverage: {', '.join(answer[required].known)}"
    if answer[required].answer is Answer.UNKNOWN and not allow_unknown:
        return unknown(f"whether CI measures {required} coverage", answer.unknowns, *coarser, known)
    return Result.failed(f"no {required} coverage measurement found in what CI runs", *coarser, known)


def _reached(granularity: Granularity, found: GranularityAnswer) -> str:
    """`branch coverage is gated with gcovr`: the highest rung reached, with the tools that reach it."""
    rung = found.rung or Rung.MEASURED
    return f"{granularity} coverage is {rung} with {', '.join(found.at(rung))}"


def _next_rungs(granularity: Granularity, found: GranularityAnswer) -> tuple[str, ...]:
    """What is suggested after the required coverage is measured: to report it, and to gate on it."""
    rung = found.rung or Rung.MEASURED
    hints = {
        Rung.REPORTED: f"consider reporting {granularity} coverage where it can be seen (a report CI publishes, "
        "a coverage service)",
        Rung.GATED: f"consider failing CI when {granularity} coverage falls below a threshold",
    }
    return tuple(hint for next_rung, hint in hints.items() if next_rung.rank > rung.rank)


def judge_coverage(answer: CoverageAnswer, *, allow_unknown: bool = False) -> Result:
    """Required coverage passes, and path coverage is a bonus where a known tool measures it; a language no known
    tool measures is skipped. An unknown answer is an error unless `allow_unknown`."""
    required = required_coverage(answer)
    if required is None:
        return Result.skipped(f"no known tool measures the coverage of {answer.language}")
    if answer[required].answer is not Answer.YES:
        return _missing(answer, required, allow_unknown=allow_unknown)
    message = _reached(required, answer[required])
    hints = _next_rungs(required, answer[required])
    path = answer[Granularity.PATH]
    if path.answer is Answer.YES:
        rung = path.rung or Rung.MEASURED
        bonus = f"{rung} with {', '.join(path.at(rung))}" + (" (not reported)" if rung is Rung.MEASURED else "")
        return Result.passed(f"{message}; path coverage bonus: {bonus}", *hints)
    if path.answer is Answer.IMPOSSIBLE:
        return Result.passed(message, *hints)
    return Result.passed(message, *hints, f"consider adding path coverage (e.g. {', '.join(path.known)})")


__all__ = ["judge_coverage", "required_coverage"]
