"""The static analysis and type checking policies: CI runs an analyzer (every required one, with its checks defined)
and a type checker; strict type checking is a bonus."""

from project_validator.core import Result, Status
from project_validator.facts.analysis import CHECKS, Strictness
from project_validator.policy import both, either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def _named(answer: ToolAnswer, tool: str) -> str:
    """A tool, with the files that define it."""
    files = answer.definitions((tool,))
    return f"{tool} ({', '.join(files)})" if files else tool


def _ran(answer: ToolAnswer) -> str:
    running = [_named(answer, tool) for tool in answer.providing()]
    return f"{both(running)} {'runs' if len(running) == 1 else 'run'}"


def _idle(answer: ToolAnswer, tools: tuple[str, ...]) -> list[str]:
    """Each of `tools`, which CI does not run, as configured or not."""
    return [
        f"{tool} is configured ({', '.join(files)}) but does not run"
        if (files := answer.definitions((tool,)))
        else f"{tool} does not run"
        for tool in tools
    ]


def _analysis_hint(answer: ToolAnswer) -> str:
    ways = answer.how(CHECKS)
    joined = both(ways) if any(tool.required for tool in answer.known) else either(ways)
    return f"consider running {joined} in CI"


def judge_analysis(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Static analysis passes when CI runs an analyzer, and every required one, with its checks defined where it has
    no defaults of its own; defined but not run warns. An unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known static analyzer handles {answer.language}")
    hint = _analysis_hint(answer)
    if answer.answer is Answer.YES:
        undefined = answer.undefined()
        defaults = (f"{tool} has no configuration of its checks, so it runs only its defaults" for tool in undefined)
        problems = [*_idle(answer, answer.required_idle()), *defaults]
        if problems:
            return Result.warned(f"{_ran(answer)}, but {'; '.join(problems)}", hint)
        return Result.passed(_ran(answer))
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI runs a static analyzer", answer.unknowns, hint)
    if configured := [name for name, _ in answer.defined]:
        return Result.warned("; ".join(_idle(answer, tuple(configured))), hint)
    return Result.failed("no static analyzer runs", hint)


def judge_type_checking(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Type checking passes when CI runs a type checker, and strict mode is a bonus; configured but not run warns. An
    unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result(status=Status.SKIP, message=f"no known type checker handles {answer.language}")
    hint = f"consider running a type checker in CI: {either(answer.how(Strictness.CHECKS))}"
    if answer.answer is Answer.YES:
        if strict := answer.providing(Strictness.STRICT):
            where = (f"{tool} ({', '.join(read)})" if (read := answer.read_by(tool)) else tool for tool in strict)
            return Result.passed(f"{_ran(answer)}; strict mode bonus: {', '.join(where)}")
        return Result.passed(_ran(answer), f"consider enabling strict mode: {either(answer.how(Strictness.STRICT))}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI runs a type checker", answer.unknowns, hint)
    if configured := [name for name, _ in answer.defined]:
        return Result.warned("; ".join(_idle(answer, tuple(configured))), hint)
    return Result.failed("no type checker runs", hint)


__all__ = ["judge_analysis", "judge_type_checking"]
