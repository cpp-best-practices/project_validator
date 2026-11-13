"""The tests policy: the project has tests, and CI runs them."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.facts.testing import RUNS
from project_validator.policy import either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def judge_tests(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Tests must exist (as each language's runners define them) and CI must run them; tests CI never runs warn. An
    unknown answer is an error unless `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result.skipped(f"no known test runner runs {answer.language}")
    files = answer.definitions()
    if not files and answer.unknown_definitions and not allow_unknown:
        return unknown("whether there are tests", answer.unknown_definitions)
    if not files:
        # The kinds, not the runners' descriptions: two runners of the same kinds say them once.
        kinds = dict.fromkeys(kind for tool in answer.known for kind in (tool.kinds or (tool.describe,)) if kind)
        return Result.failed(f"no tests found ({either(kinds)})" if kinds else "no tests found")
    found = f"tests found in {len(files)} file(s)"
    if answer.answer is Answer.YES:
        return Result.passed(found)
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI runs the tests", answer.unknowns)
    return Result.warned(f"{found}, but no CI configuration runs {either(answer.how(RUNS))}")


__all__ = ["judge_tests"]
