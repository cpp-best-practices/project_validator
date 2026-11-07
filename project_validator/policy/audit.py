"""The dependency audit policy: CI checks the dependencies against known vulnerabilities."""

from project_validator.core import Result, Status
from project_validator.facts.audit import RUNS
from project_validator.policy import either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def judge_audit(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """An audit passes; none warns (dependencies change under a project, so this is advice more than a defect). An
    unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known tool audits the dependencies of {answer.language}")
    if answer.answer is Answer.YES:
        return Result.passed(f"CI audits the dependencies with {', '.join(answer.providing())}")
    hint = f"consider running in CI: {either(answer.how(RUNS))}"
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI audits the dependencies", answer.unknowns, hint)
    return Result.warned("no dependency vulnerability audit found in CI configuration", hint)


__all__ = ["judge_audit"]
