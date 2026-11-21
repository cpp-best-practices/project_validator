"""The tests policy: the project has tests, and CI runs them."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.facts.testing import RUNS
from project_validator.policy import both, either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def judge_tests(answer: ToolAnswer, *, allow_unknown: bool) -> Result:
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
    found = f"{_kinds(answer) or 'tests'}: {len(files)} file(s){_lent(answer)}"
    if answer.answer is Answer.YES:
        return Result.passed(f"{found}, run by {both(answer.providing())}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI runs the tests", answer.unknowns)
    return Result.warned(f"{found}, but no CI configuration runs {either(answer.how(RUNS))}")


def _lent(answer: ToolAnswer) -> str:
    """Whose the files are, when units of tests lend them all (tokio's benches have none of their own)."""
    return f" in {', '.join(answer.lent_by)}" if answer.lent_by else ""


def _kinds(answer: ToolAnswer) -> str:
    """What the files found are, as the runners that define tests by them say (`busted specs (spec/**/*_spec.lua)`,
    the mkdocs site's configuration)."""
    defining = {name for name, paths in answer.defined if paths}
    kinds = (kind for tool in answer.known if tool.name in defining for kind in (tool.kinds or (tool.describe,)))
    return both(dict.fromkeys(kind for kind in kinds if kind))


__all__ = ["judge_tests"]
