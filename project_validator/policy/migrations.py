"""The migration-safety policy: a project with database migrations has CI check them for changes that are unsafe to
apply to a live database (a lock held on a busy table, a column dropped); none warns, as the migrations may be run
against a copy first, which the validator cannot see. A project without migrations has nothing to judge."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.facts.migrations import LINTED
from project_validator.policy import both, either, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def judge_migration_safety(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Migrations must be checked by a migration linter CI runs; none warns. An unknown answer is an error unless
    `allow_unknown`."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result.skipped(f"no known tool checks {answer.language} migrations")
    migrations = answer.definitions()
    if not migrations and answer.unknown_definitions and not allow_unknown:
        return unknown("whether there are migrations", answer.unknown_definitions)
    if not migrations:
        return Result.skipped("no migrations to judge")
    found = f"{len(migrations)} migration file{'s' * (len(migrations) != 1)}"
    if answer.answer is Answer.YES:
        return Result.passed(f"CI checks the {found} for unsafe changes with {both(answer.providing())}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI checks the migrations for unsafe changes", answer.unknowns)
    return Result.warned(
        f"{found}, but no CI configuration checks them for unsafe changes",
        f"consider running {either(answer.how(LINTED))}",
    )


__all__ = ["judge_migration_safety"]
