"""The settings policies: every setting of the strict warning set is on (for each compiler CI builds with), and
warnings fail the build in at least one configuration."""

from collections.abc import Callable, Iterable

from project_validator.core import Result, Status
from project_validator.policy import unknown
from project_validator.questions import Answer
from project_validator.questions.practices import Compiled, PracticeAnswer


def _described(
    compiled: tuple[Compiled, ...], names: Callable[[Compiled], tuple[str, ...]], joined: Callable[[Iterable[str]], str]
) -> str:
    """The `names` of each compiler, joined; compilers that have the same are named together, and when all of them
    have the same, none is named."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for compiled_for in compiled:
        if found := names(compiled_for):
            groups.setdefault(found, []).append(compiled_for.compiler or "")
    if len(groups) == 1 and len(next(iter(groups.values()))) == len(compiled):
        return joined(next(iter(groups)))
    return "; ".join(f"{joined(found)} for {' and '.join(compilers)}" for found, compilers in groups.items())


def _found(compiled: Compiled) -> tuple[str, ...]:
    return tuple(name for name, _ in compiled.found)


def _missing(compiled: Compiled) -> tuple[str, ...]:
    return compiled.missing


def judge_warnings(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """Every setting on passes; some on warns, naming those missing; none fails. Unknown is an error unless
    `allow_unknown`."""
    practice = answer.practice
    joined = practice.separator.join
    if answer.answer is Answer.YES:
        return Result.passed(f"strict {practice.kind} are enabled: {_described(answer.compiled, _found, joined)}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown(f"whether the strict {practice.kind} are enabled", answer.unknowns, practice.hint)
    if not answer.found():
        required = dict.fromkeys(name for compiled in answer.compiled for name in compiled.missing)
        return Result.failed(f"no {practice.kind} found; enable at least {joined(required)}")
    missing = _described(answer.compiled, _missing, ", ".join)
    return Result.warned(f"missing {practice.kind}: {missing}", f"found {joined(answer.found())}")


def judge_hardening(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """Every hardening setting on passes (or, for a practice that forbids settings, none found); some on warns; none
    fails. A language whose project builds no binary is skipped. Unknown is an error unless `allow_unknown`."""
    practice = answer.practice
    joined = practice.separator.join
    if answer.skipped is not None:
        return Result(status=Status.SKIP, message=answer.skipped)
    if answer.answer is Answer.YES:
        enabled = practice.passed or f"{practice.kind} are enabled: {_described(answer.compiled, _found, joined)}"
        return Result.passed(enabled)
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        asked = f"whether {practice.kind} are kept" if practice.forbids else f"whether the {practice.kind} are enabled"
        return unknown(asked, answer.unknowns, practice.hint)
    if practice.forbids:
        return Result.failed(f"{practice.failed}: {joined(answer.found())}", practice.hint)
    if not answer.found():
        required = dict.fromkeys(name for compiled in answer.compiled for name in compiled.missing)
        return Result.failed(practice.failed or f"no {practice.kind} found; enable {joined(required)}", practice.hint)
    missing = _described(answer.compiled, _missing, ", ".join)
    return Result.warned(f"missing {practice.kind}: {missing}", f"found {joined(answer.found())}")


def judge_errors(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """Warnings that fail the build in some configuration pass; none fails. Unknown is an error unless
    `allow_unknown`."""
    practice = answer.practice
    if answer.answer is Answer.YES:
        return Result.passed(f"warnings are treated as errors with {', '.join(answer.found())}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether warnings are treated as errors", answer.unknowns, practice.hint)
    return Result.failed(f"warnings are not treated as errors in {practice.searched}", practice.hint)


__all__ = ["judge_errors", "judge_hardening", "judge_warnings"]
