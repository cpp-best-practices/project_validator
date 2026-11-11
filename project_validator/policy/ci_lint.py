"""The CI lint policy: each CI provider with a known configuration linter has it run; a provider none is known for is
not judged."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.questions import Answer
from project_validator.questions.ci_lint import CiLintAnswer


def judge_ci_lint(answer: CiLintAnswer, *, allow_unknown: bool = False) -> Result:
    """Every lintable provider linted passes; one not warns, with how to lint it; no lintable provider is skipped."""
    del allow_unknown  # the linters are searched for in the configuration text itself: nothing is hidden
    if answer.answer is Answer.IMPOSSIBLE:
        if not answer.providers:
            return Result.skipped("no CI configuration")
        names = ", ".join(found.provider for found in answer.providers)
        return Result.skipped(f"no configuration linter is known for {names}")
    if missing := [found for found in answer.lintable() if not found.linters]:
        names = ", ".join(found.provider for found in missing)
        return Result.warned(f"CI does not lint its {names} configuration", *(found.hint for found in missing))
    listed = "; ".join(f"{found.provider}: {', '.join(found.linters)}" for found in answer.lintable())
    return Result.passed(f"CI lints its configuration ({listed})")


__all__ = ["judge_ci_lint"]
