"""Policies over the shared tool model (see `project_validator.questions.tooling`) with one level: a run of a tool of
the aspect passes; none warns (`advised`) or fails (`required`), with how to add one."""

from __future__ import annotations

from collections.abc import Callable

from project_validator.core import Result
from project_validator.policy import Judge, either, skipped_or_unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def advised(*, level: str, impossible: str, passed: str, asks: str, missing: str) -> Judge[ToolAnswer]:
    """A policy that passes when CI provides `level` (`passed`, with `{tools}` for those that do) and warns when it
    does not (`missing`), each with how to add a tool. `impossible` (with `{language}`) when no known tool handles
    the language; `asks` is what an unknown answer leaves open."""
    return _one_level(Result.warned, level=level, impossible=impossible, passed=passed, asks=asks, missing=missing)


def required(*, level: str, impossible: str, passed: str, asks: str, missing: str) -> Judge[ToolAnswer]:
    """As `advised`, but CI not providing `level` fails."""
    return _one_level(Result.failed, level=level, impossible=impossible, passed=passed, asks=asks, missing=missing)


def _one_level(
    without: Callable[[str, str], Result], *, level: str, impossible: str, passed: str, asks: str, missing: str
) -> Judge[ToolAnswer]:
    def judge(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
        hint = f"consider running in CI: {either(answer.how(level))}"
        settled = skipped_or_unknown(
            answer.answer,
            answer.unknowns,
            impossible=impossible.format(language=answer.language),
            asks=asks,
            hint=hint,
            allow_unknown=allow_unknown,
        )
        if settled is not None:
            return settled
        if answer.answer is Answer.YES:
            return Result.passed(passed.format(tools=", ".join(answer.providing())))
        return without(missing, hint)

    return judge


__all__ = ["advised", "required"]
