"""Warnings fail the build, in at least one configuration."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import error_answers

warnings_as_errors = answered_check(
    name=PracticeName.WARNINGS_AS_ERRORS,
    description="Compiler warnings are treated as errors in at least one configuration",
    languages=handled(PracticeName.WARNINGS_AS_ERRORS),
    answers=error_answers,
    judge=judge_any_one,
)
