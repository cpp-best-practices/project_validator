"""Policy: how answers (see `project_validator.questions`) are judged. Built in for now; kept apart from the questions
so that it can be made configurable without touching extraction."""

from project_validator.core import Result, Status
from project_validator.facts.coverage import Granularity
from project_validator.questions import Answer
from project_validator.questions.coverage import CoverageAnswer


def required_coverage(answer: CoverageAnswer) -> Granularity | None:
    """Branch coverage, or the finest a known tool measures for the language when none measures branches; None when
    no known tool measures the language's coverage at all."""
    possible = [found for found in answer.possible() if found.rank <= Granularity.BRANCH.rank]
    return possible[-1] if possible else None


def _missing(answer: CoverageAnswer, required: Granularity) -> Result:
    coarser = (
        f"{granularity} coverage is reported with {', '.join(answer[granularity].tools)}"
        for granularity in answer.possible()
        if granularity.rank < required.rank and answer[granularity].answer is Answer.YES
    )
    known = f"known to report {required} coverage: {', '.join(answer[required].known)}"
    if answer[required].answer is Answer.UNKNOWN:
        unread = (f"not read: {unknown}" for unknown in answer.unknowns)
        return Result.failed(
            f"no {required} coverage reporting found in what CI runs that could be read", *coarser, known, *unread
        )
    return Result.failed(f"no {required} coverage reporting found in what CI runs", *coarser, known)


def judge_coverage(answer: CoverageAnswer) -> Result:
    """Required coverage passes, and path coverage is a bonus where a known tool measures it; a language no known
    tool measures is skipped."""
    required = required_coverage(answer)
    if required is None:
        return Result(status=Status.SKIP, message=f"no known tool measures the coverage of {answer.language}")
    if answer[required].answer is not Answer.YES:
        return _missing(answer, required)
    message = f"{required} coverage is reported with {', '.join(answer[required].tools)}"
    path = answer[Granularity.PATH]
    if path.answer is Answer.YES:
        return Result.passed(f"{message}; path coverage bonus: {', '.join(path.tools)}")
    if path.answer is Answer.IMPOSSIBLE:
        return Result.passed(message)
    return Result.passed(message, f"consider adding path coverage (e.g. {', '.join(path.known)})")


__all__ = ["judge_coverage", "required_coverage"]
