"""The schema validation question: for each format, in each unit of the project that has it, does CI validate its
documents against their schemas?"""

from __future__ import annotations

from project_validator.facts.schema import SCHEMA, VALIDATES
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

schema_validation = aspect_answers(SCHEMA, VALIDATES)
SCHEMA_VALIDATION_QUESTION = Question(
    name="schema-validation",
    description="Does CI validate each format's documents in each unit against their schemas?",
    answer=schema_validation,
)

__all__ = ["SCHEMA_VALIDATION_QUESTION", "schema_validation"]
