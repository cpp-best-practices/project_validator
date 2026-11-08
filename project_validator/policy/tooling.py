"""Policies over the shared tool model (see `project_validator.questions.tooling`) that only advise: a run of a tool
of the aspect passes, and none warns, with how to add one."""

from project_validator.core import Result
from project_validator.policy import Judge, either, skipped_or_unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def advised(*, level: str, impossible: str, passed: str, asks: str, missing: str) -> Judge[ToolAnswer]:
    """A policy that passes when CI provides `level` (`passed`, with `{tools}` for those that do) and warns when it
    does not (`missing`), each with how to add a tool. `impossible` (with `{language}`) when no known tool handles
    the language; `asks` is what an unknown answer leaves open."""

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
        return Result.warned(missing, hint)

    return judge


__all__ = ["advised"]
