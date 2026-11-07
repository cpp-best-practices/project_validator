"""Policy: how answers (see `project_validator.questions`) are judged. Built in, apart from `--allow-unknown`; kept
apart from the questions so that it can be made configurable without touching extraction.

An unknown answer is a gap in the validator's tooling (configuration it cannot read), not a finding about the
project, so it is an error unless the user allows unknowns; then it is judged by what could be read.
"""

from project_validator.core import Result, Status
from project_validator.facts.coverage import Granularity
from project_validator.questions import Answer
from project_validator.questions.coverage import CoverageAnswer


def required_coverage(answer: CoverageAnswer) -> Granularity | None:
    """Branch coverage, or the finest a known tool measures for the language when none measures branches; None when
    no known tool measures the language's coverage at all."""
    possible = [found for found in answer.possible() if found.rank <= Granularity.BRANCH.rank]
    return possible[-1] if possible else None


def _missing(answer: CoverageAnswer, required: Granularity, *, allow_unknown: bool) -> Result:
    coarser = (
        f"{granularity} coverage is reported with {', '.join(answer[granularity].tools)}"
        for granularity in answer.possible()
        if granularity.rank < required.rank and answer[granularity].answer is Answer.YES
    )
    known = f"known to report {required} coverage: {', '.join(answer[required].known)}"
    if answer[required].answer is Answer.UNKNOWN and not allow_unknown:
        return Result(
            status=Status.ERROR,
            message=f"whether CI reports {required} coverage is unknown: some of what it runs could not be read",
            details=(
                *(f"not read: {unknown}" for unknown in answer.unknowns),
                *coarser,
                known,
                "--allow-unknown judges only what could be read",
            ),
        )
    return Result.failed(f"no {required} coverage reporting found in what CI runs", *coarser, known)


def judge_coverage(answer: CoverageAnswer, *, allow_unknown: bool = False) -> Result:
    """Required coverage passes, and path coverage is a bonus where a known tool measures it; a language no known
    tool measures is skipped. An unknown answer is an error unless `allow_unknown`."""
    required = required_coverage(answer)
    if required is None:
        return Result(status=Status.SKIP, message=f"no known tool measures the coverage of {answer.language}")
    if answer[required].answer is not Answer.YES:
        return _missing(answer, required, allow_unknown=allow_unknown)
    message = f"{required} coverage is reported with {', '.join(answer[required].tools)}"
    path = answer[Granularity.PATH]
    if path.answer is Answer.YES:
        return Result.passed(f"{message}; path coverage bonus: {', '.join(path.tools)}")
    if path.answer is Answer.IMPOSSIBLE:
        return Result.passed(message)
    return Result.passed(message, f"consider adding path coverage (e.g. {', '.join(path.known)})")


__all__ = ["judge_coverage", "required_coverage"]
