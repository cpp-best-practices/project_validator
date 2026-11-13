"""The schema questions: for each format, in each unit of the project that has it, does CI validate its documents
against their schemas, does CI check the examples that come with the schemas, and does CI check the schemas for
breaking changes?"""

from __future__ import annotations

from project_validator.facts.schema import BREAKING, CHECKED, COMPATIBILITY, EXAMPLES, SCHEMA, VALIDATES
from project_validator.questions import EVERY_KIND, Question
from project_validator.questions.tooling import aspect_answers

schema_validation = aspect_answers(SCHEMA, VALIDATES)
SCHEMA_VALIDATION_QUESTION = Question(
    name="schema-validation",
    description="Does CI validate each format's documents in each unit against their schemas?",
    answer=schema_validation,
    kinds=EVERY_KIND,
)

schema_examples = aspect_answers(EXAMPLES, CHECKED)
SCHEMA_EXAMPLES_QUESTION = Question(
    name="schema-examples",
    description="Does CI check the examples that come with each format's schemas in each unit?",
    answer=schema_examples,
    kinds=EVERY_KIND,
)

schema_compatibility = aspect_answers(COMPATIBILITY, BREAKING)
SCHEMA_COMPATIBILITY_QUESTION = Question(
    name="schema-compatibility",
    description="Does CI check each format's schemas in each unit for breaking changes?",
    answer=schema_compatibility,
    kinds=EVERY_KIND,
)

__all__ = [
    "SCHEMA_COMPATIBILITY_QUESTION",
    "SCHEMA_EXAMPLES_QUESTION",
    "SCHEMA_VALIDATION_QUESTION",
    "schema_compatibility",
    "schema_examples",
    "schema_validation",
]
