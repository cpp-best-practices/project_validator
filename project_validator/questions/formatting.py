"""The formatting question: for each language, in each unit of the project that has it, does CI enforce the
formatting (a formatter run that checks it), and where is it defined?"""

from __future__ import annotations

from project_validator.facts.formatting import FORMAT, Enforcement
from project_validator.questions import EVERY_KIND, Question
from project_validator.questions.tooling import aspect_answers

formatting = aspect_answers(FORMAT, Enforcement.CHECK)
FORMATTING_QUESTION = Question(
    name="formatting",
    description="Does CI enforce the formatting of each language in each unit, and where is the formatting defined?",
    answer=formatting,
    kinds=EVERY_KIND,
)

__all__ = ["FORMATTING_QUESTION", "formatting"]
