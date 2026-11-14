"""The migration-safety question: for each language with database migrations, in each unit of the project that has
it, are there migrations, and does CI check them for changes that are unsafe to apply to a live database?"""

from __future__ import annotations

from project_validator.facts.migrations import LINTED, MIGRATIONS
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

migration_safety = aspect_answers(MIGRATIONS, LINTED)
MIGRATION_SAFETY_QUESTION = Question(
    name="migration-safety",
    description="Are there database migrations for each language in each unit, and does CI check them for unsafe "
    "changes?",
    answer=migration_safety,
)

__all__ = ["MIGRATION_SAFETY_QUESTION", "migration_safety"]
