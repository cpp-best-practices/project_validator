from __future__ import annotations

from project_validator.facts.testing import TEST
from project_validator.judging import answered_check
from project_validator.policy.testing import judge_tests
from project_validator.questions.testing import tests

tests_run = answered_check(
    name="tests-run",
    description="Tests exist (registered with CTest or Meson for C and C++) and CI runs them",
    aspect=TEST,
    answers=tests,
    judge=judge_tests,
    aliases=("ctest-runs",),
    # A unit the map names auxiliary is asked for tests it has: a cargo-fuzz crate need hold none (upstream #230).
    auxiliary_unit=lambda answer: bool(answer.definitions() or answer.unknown_definitions),
)
