"""A strict warning set is on: each language's compiler warnings (or the linters that report what other compilers
warn about), for each compiler CI builds with where a language has several."""

from project_validator.facts.practices import WARNINGS, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_warnings
from project_validator.questions.practices import warning_answers

compiler_warnings = answered_check(
    name=WARNINGS,
    description="A strict compiler warning (or lint) set is enabled",
    languages=handled(WARNINGS),
    answers=warning_answers,
    judge=judge_warnings,
)
