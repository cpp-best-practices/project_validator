"""Policy: how answers (see `project_validator.questions`) are judged. Built in, apart from `--allow-unknown`; kept
apart from the questions so that it can be made configurable without touching extraction.

An unknown answer is a gap in the validator's tooling (configuration it cannot read), not a finding about the
project, so it is an error unless the user allows unknowns; then it is judged by what could be read.
"""

from collections.abc import Iterable

from project_validator.core import Result, Status
from project_validator.facts.coverage import Granularity
from project_validator.questions import Answer
from project_validator.questions.coverage import CoverageAnswer
from project_validator.questions.formatting import FormattingAnswer

_ALLOW_UNKNOWN = "--allow-unknown judges only what could be read"


def _unknown(message: str, unknowns: Iterable[str], *details: str) -> Result:
    """The error an unknown answer is: what could not be read, then what could."""
    return Result(
        status=Status.ERROR,
        message=f"{message} is unknown: some of what it runs could not be read",
        details=(*(f"not read: {unknown}" for unknown in unknowns), *details, _ALLOW_UNKNOWN),
    )


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
        return _unknown(f"whether CI reports {required} coverage", answer.unknowns, *coarser, known)
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


def _either(items: list[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


def _alternatives(ways: list[str]) -> str:
    return ways[0] if len(ways) == 1 else f"{ways[0]} (or {_either(ways[1:])})"


def _formatting_hint(answer: FormattingAnswer) -> str:
    return f"consider a CI job that runs {_alternatives([how for _, how in answer.known])}"


def _enforced(answer: FormattingAnswer) -> Result:
    tools = ", ".join(answer.tools)
    if answer.undefined:
        missing = _either(list(answer.undefined))
        return Result.failed(f"no {missing} configuration found; formatting is not defined", _formatting_hint(answer))
    files = [path for tool, paths in answer.defined if tool in answer.tools for path in paths]
    if files:
        return Result.passed(f"{', '.join(dict.fromkeys(files))} is defined and CI runs {tools}")
    return Result.passed(f"CI enforces the {tools} style")


def judge_formatting(answer: FormattingAnswer, *, allow_unknown: bool = False) -> Result:
    """Formatting passes when CI enforces it with a tool whose style is defined (by a file, or by default); defined
    but not enforced warns. A language no known tool formats is skipped. An unknown answer is an error unless
    `allow_unknown`."""
    if answer.enforced is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known tool formats {answer.language}")
    if answer.enforced is Answer.YES:
        return _enforced(answer)
    hint = _formatting_hint(answer)
    names = _either([name for name, _ in answer.known])
    if answer.enforced is Answer.UNKNOWN and not allow_unknown:
        return _unknown("whether CI enforces the formatting", answer.unknowns, hint)
    if answer.applied:
        applied = ", ".join(answer.applied)
        return Result.failed(
            f"CI runs {applied} but only to rewrite files; nothing fails when they are not formatted", hint
        )
    if answer.defined:
        files = ", ".join(dict.fromkeys(path for _, paths in answer.defined for path in paths))
        return Result.warned(f"{files} is defined but CI does not run {names}", hint)
    if not answer.default_style:
        return Result.failed(f"no {names} configuration found; formatting is not defined", hint)
    return Result.failed(f"CI never runs {names}; its formatting is not enforced", hint)


__all__ = ["judge_coverage", "judge_formatting", "required_coverage"]
