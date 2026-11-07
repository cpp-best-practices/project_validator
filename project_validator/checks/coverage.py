from project_validator.facts.coverage import COVERAGE
from project_validator.facts.tools import handling
from project_validator.judging import answered_check
from project_validator.policy.coverage import judge_coverage
from project_validator.questions.coverage import language_coverage

coverage = answered_check(
    name="coverage",
    description="CI reports branch coverage (or the finest the language's tools measure; path coverage is a bonus)",
    languages=handling(COVERAGE),
    answers=language_coverage,
    judge=lambda answer, allow_unknown: judge_coverage(answer, allow_unknown=allow_unknown),
)
