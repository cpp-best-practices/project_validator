"""The tests question: for each language, in each unit of the project that has it, are there tests, and does CI run
them?"""

from __future__ import annotations

from project_validator.facts.testing import RUNS, TEST
from project_validator.questions import EVERY_KIND, Question
from project_validator.questions.tooling import aspect_answers

tests = aspect_answers(TEST, RUNS)
TESTS_QUESTION = Question(
    name="tests",
    description="Are there tests of each language in each unit, and does CI run them?",
    answer=tests,
    kinds=EVERY_KIND,
)

__all__ = ["TESTS_QUESTION", "tests"]
