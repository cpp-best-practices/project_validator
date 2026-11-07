"""The formatting policy: CI enforces the formatting with a tool whose style is defined, by a file or by default."""

from project_validator.core import Result, Status
from project_validator.facts.formatting import Enforcement
from project_validator.policy import alternatives, either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def _hint(answer: ToolAnswer) -> str:
    return f"consider a CI job that runs {alternatives(answer.how(Enforcement.CHECK))}"


def _enforced(answer: ToolAnswer) -> Result:
    tools = ", ".join(answer.providing())
    if undefined := answer.undefined():
        return Result.failed(f"no {either(undefined)} configuration found; formatting is not defined", _hint(answer))
    if files := answer.definitions(answer.providing()):
        return Result.passed(f"{', '.join(files)} is defined and CI runs {tools}")
    return Result.passed(f"CI enforces the {tools} style")


def judge_formatting(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Formatting passes when CI enforces it with a tool whose style is defined (by a file, or by default); defined
    but not enforced warns. A language no known tool formats is skipped. An unknown answer is an error unless
    `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known tool formats {answer.language}")
    if answer.answer is Answer.YES:
        return _enforced(answer)
    hint, names = _hint(answer), either(answer.names())
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI enforces the formatting", answer.unknowns, hint)
    if applied := answer.others():
        return Result.failed(
            f"CI runs {', '.join(applied)} but only to rewrite files; nothing fails when they are not formatted", hint
        )
    if files := answer.definitions():
        return Result.warned(f"{', '.join(files)} is defined but CI does not run {names}", hint)
    if all(tool.needs_definition for tool in answer.known):
        return Result.failed(f"no {names} configuration found; formatting is not defined", hint)
    return Result.failed(f"CI never runs {names}; its formatting is not enforced", hint)


__all__ = ["judge_formatting"]
