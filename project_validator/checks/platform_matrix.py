"""CI runs on several operating systems with several compilers (or interpreter and toolchain versions)."""

from project_validator.facts.axes import handled
from project_validator.judging import answered_check
from project_validator.policy.platforms import judge_matrix
from project_validator.questions.platforms import platform_answers

platform_matrix = answered_check(
    name="platform-matrix",
    description="CI runs on several operating systems with several compilers (or interpreter/toolchain versions)",
    languages=handled(),
    answers=platform_answers,
    judge=judge_matrix,
)
