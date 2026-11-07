"""The code security scanning policy: CI scans the code, with a multi-language scanner or the language's own security
lints."""

from project_validator.core import Result, Status
from project_validator.facts.security import SCANS
from project_validator.policy import either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def judge_security(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """A scan passes; none warns. An unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known tool scans {answer.language} for security problems")
    if answer.answer is Answer.YES:
        return Result.passed(f"CI scans the code for security problems with {', '.join(answer.providing())}")
    hint = f"consider running in CI: {either(answer.how(SCANS))}"
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI scans the code for security problems", answer.unknowns, hint)
    return Result.warned("no code security scanning found in CI configuration", hint)


__all__ = ["judge_security"]
