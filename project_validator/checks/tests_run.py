from project_validator.facts.testing import TEST
from project_validator.facts.tools import handling
from project_validator.judging import answered_check
from project_validator.policy.testing import judge_tests
from project_validator.questions.testing import tests

tests_run = answered_check(
    name="tests-run",
    description="Tests exist (registered with CTest or Meson for C/C++) and CI runs them",
    languages=handling(TEST),
    answers=tests,
    judge=lambda answer, allow_unknown: judge_tests(answer, allow_unknown=allow_unknown),
    aliases=("ctest-runs",),
)
