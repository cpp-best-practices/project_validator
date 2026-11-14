"""CI checks the database migrations for changes that are unsafe to apply to a live database: squawk on Postgres
migrations (locking and destructive statements), `atlas migrate lint`, `liquibase checks run`. A project without
migrations is not judged."""

from __future__ import annotations

from project_validator.facts.migrations import MIGRATIONS
from project_validator.judging import answered_check
from project_validator.policy.migrations import judge_migration_safety
from project_validator.questions.migrations import migration_safety as migration_answers

migration_safety = answered_check(
    name="migration-safety",
    description="CI checks each language's database migrations in each unit for changes that are unsafe to apply to "
    "a live database (squawk, atlas migrate lint, liquibase checks run). Warns otherwise; a project without migrations "
    "is not judged",
    aspect=MIGRATIONS,
    answers=migration_answers,
    judge=judge_migration_safety,
)
