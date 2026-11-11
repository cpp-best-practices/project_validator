"""The settings policies: every setting of the strict warning set is on (for each compiler CI builds with), and
warnings fail the build in at least one configuration. Each is worded as the practice says (`Wording`): what the
settings are called, how to set them, and the sentences the profile replaces where the policy's do not fit."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from project_validator.core import Result
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


def _required(answer: PracticeAnswer) -> dict[str, None]:
    return dict.fromkeys(name for compiled in answer.compiled for name in compiled.missing)


def judge_warnings(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """Every setting on passes; some on warns, naming those missing; none fails. Unknown is an error unless
    `allow_unknown`."""
    words = answer.practice.words
    joined = words.separator.join
    if answer.answer is Answer.YES:
        return Result.passed(f"strict {words.kind} are enabled: {_described(answer.compiled, _found, joined)}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown(f"whether the strict {words.kind} are enabled", answer.unknowns, words.hint)
    if not answer.found():
        return Result.failed(f"no {words.kind} found; enable at least {joined(_required(answer))}")
    missing = _described(answer.compiled, _missing, ", ".join)
    return Result.warned(f"missing {words.kind}: {missing}", f"found {joined(answer.found())}")


def judge_hardening(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """Every hardening setting on passes (or, for a practice that forbids settings, none found); some on warns; none
    fails. A language whose project builds no binary is skipped. Unknown is an error unless `allow_unknown`."""
    practice, words = answer.practice, answer.practice.words
    joined = words.separator.join
    if answer.skipped is not None:
        return Result.skipped(answer.skipped)
    if answer.answer is Answer.YES:
        return Result.passed(words.passed or f"{words.kind} are enabled: {_described(answer.compiled, _found, joined)}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        asked = f"whether {words.kind} are kept" if practice.forbids else f"whether the {words.kind} are enabled"
        return unknown(asked, answer.unknowns, words.hint)
    if practice.forbids:
        return Result.failed(f"{words.failed}: {joined(answer.found())}", words.hint)
    if not answer.found():
        return Result.failed(words.failed or f"no {words.kind} found; enable {joined(_required(answer))}", words.hint)
    missing = _described(answer.compiled, _missing, ", ".join)
    return Result.warned(f"missing {words.kind}: {missing}", f"found {joined(answer.found())}")


def judge_any_one(answer: PracticeAnswer, *, allow_unknown: bool = False) -> Result:
    """A setting met in some configuration passes (with advice when only one that is not preferred is); none fails.
    Unknown is an error unless `allow_unknown`."""
    words = answer.practice.words
    found = ", ".join(answer.found())
    if answer.skipped is not None:
        return Result.skipped(answer.skipped)
    if answer.answer is Answer.YES:
        passed = (words.passed or "warnings are treated as errors with {found}").format(found=found)
        preferred_met = not words.preferred or set(words.preferred) & set(answer.found())
        return Result.passed(passed, *(() if preferred_met else (words.preference,)))
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown(words.question or "whether warnings are treated as errors", answer.unknowns, words.hint)
    return Result.failed(words.failed or f"warnings are not treated as errors in {words.searched}", words.hint)


__all__ = ["judge_any_one", "judge_hardening", "judge_warnings"]
