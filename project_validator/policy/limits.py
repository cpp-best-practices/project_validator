"""The function length policy: CI runs a tool that fails when a function is longer than a limit, lizard told a limit
or a linter whose rule is on."""

from project_validator.core import Result, Status
from project_validator.policy import either, unknown
from project_validator.policy import files as files_listed
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def _hint(answer: ToolAnswer) -> str:
    return f"consider running in CI: {either(answer.how())}"


def _limited(answer: ToolAnswer) -> Result:
    # Each tool with the files that define its limit (a `.clang-tidy`), not those that only run it (a Rakefile).
    tools = (
        f"{name} ({files_listed(defined)})" if (defined := answer.definitions((name,))) else name
        for name in answer.providing()
    )
    return Result.passed(f"function length is limited with {', '.join(tools)}")


def _without_limits(answer: ToolAnswer, running: tuple[str, ...]) -> Result:
    """CI runs limiters, but none with its limit on."""
    how = either(tuple(tool.describe for tool in answer.known if tool.name in running))
    return Result.failed(f"CI runs {', '.join(running)}, but without a function length limit; set {how}")


def judge_limits(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """A limit CI enforces passes; a limit defined that CI does not run warns; none fails. A language no known tool
    measures is skipped. An unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known tool limits the length of {answer.language} functions")
    if answer.answer is Answer.YES:
        return _limited(answer)
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI limits function length", answer.unknowns, _hint(answer))
    if running := answer.others():
        return _without_limits(answer, running)
    if files := answer.definitions():
        defining = tuple(name for name, _ in answer.defined)
        return Result.warned(
            f"{files_listed(files)} limits function length, but CI does not run {either(defining)}", _hint(answer)
        )
    return Result.failed("function length is never limited", _hint(answer))


__all__ = ["judge_limits"]
