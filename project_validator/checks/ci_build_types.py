"""CI builds each platform of a compiled language in Debug and Release, with and without sanitizers. Interpreted
languages such as Python have no build types."""

from project_validator.facts.axes import handled
from project_validator.judging import answered_check
from project_validator.policy.platforms import judge_build_types
from project_validator.questions.platforms import platform_answers

ci_build_types = answered_check(
    name="ci-build-types",
    description="CI builds Debug and Release, with and without sanitizers, everywhere",
    languages=handled(compiled=True),
    answers=platform_answers,
    judge=judge_build_types,
)
