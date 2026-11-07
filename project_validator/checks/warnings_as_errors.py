"""Warnings fail the build, in at least one configuration."""

from project_validator.facts.practices import WARNINGS_AS_ERRORS, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_errors
from project_validator.questions.practices import error_answers

warnings_as_errors = answered_check(
    name=WARNINGS_AS_ERRORS,
    description="Compiler warnings are treated as errors in at least one configuration",
    languages=handled(WARNINGS_AS_ERRORS),
    answers=error_answers,
    judge=lambda answer, allow_unknown: judge_errors(answer, allow_unknown=allow_unknown),
)
