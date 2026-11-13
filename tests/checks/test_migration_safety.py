"""The migration-safety check: a project with database migrations has CI check them for unsafe changes, or warns; a
project without migrations is not judged."""

from __future__ import annotations

import unittest

from project_validator.checks.migration_safety import migration_safety
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Result, Status
from project_validator.facts.migrations import LINTED, MIGRATIONS, is_migration
from project_validator.policy.migrations import judge_migration_safety
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer
from project_validator.runner import run_check
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project

CHECKED = "CI checks the 1 migration file for unsafe changes with {}"
NOT_CHECKED = (Status.WARN, "1 migration file, but no CI configuration checks them for unsafe changes")
LAYOUT = "SQL migrations"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class MigrationSafetyTests(unittest.TestCase):
    def test_applies_to_sql(self) -> None:
        self.assertEqual(migration_safety.aspect, MIGRATIONS)
        self.assertEqual(migration_safety.languages, frozenset({"SQL"}))

    def test_migrations_are_told_by_their_name_or_directory(self) -> None:
        for path in (
            "migrations/V1__init.sql",
            "db/migrate/20240101_orders.sql",
            "db/migrations/001_orders.sql",
            "sql/V2_1__add_index.sql",
            "sql/R__orders_view.sql",
            "sql/U2__drop_index.sql",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_migration(path))
        for path in ("schema.sql", "models/orders.sql", "migrations/README.md", "tests/orders.sql"):
            with self.subTest(path=path):
                self.assertFalse(is_migration(path))

    def test_a_migration_linter_run_passes_and_none_warns(self) -> None:
        for line, tool in (
            ("squawk migrations/*.sql", "squawk"),
            ("npx --yes squawk-cli migrations/*.sql", "squawk"),
            ("atlas migrate lint --dir file://migrations --dev-url docker://postgres/16/dev", "atlas migrate lint"),
            ("liquibase checks run --changelog-file changelog.xml", "liquibase checks"),
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    run_in_layout(self, LAYOUT, migration_safety, _ci(line)), Result.passed(CHECKED.format(tool))
                )
        for line in (
            "flyway migrate",
            "atlas migrate apply --dir file://migrations",
            "liquibase update",
            "sqlfluff lint .",
        ):
            with self.subTest(line=line):
                result = run_in_layout(self, LAYOUT, migration_safety, _ci(line))
                self.assertEqual((result.status, result.message), NOT_CHECKED)
                self.assertIn("squawk migrations/*.sql", result.details[0])

    def test_squawk_is_an_analysis_of_the_sql_too(self) -> None:
        self.assertEqual(
            run_in_layout(self, LAYOUT, static_analysis, _ci("squawk migrations/*.sql")).status, Status.PASS
        )

    def test_the_actions(self) -> None:
        failing = github_action("sbdchd/squawk-action@v1", pattern="migrations/*.sql", **{"fail-on-violations": "true"})
        self.assertEqual(
            run_in_layout(self, LAYOUT, migration_safety, failing), Result.passed(CHECKED.format("squawk"))
        )
        # By default the action comments on the pull request and fails nothing.
        commenting = github_action("sbdchd/squawk-action@v1", pattern="migrations/*.sql")
        self.assertEqual(run_in_layout(self, LAYOUT, migration_safety, commenting).status, Status.WARN)
        atlas = github_action(
            "ariga/atlas-action/migrate/lint@v1", dir="file://migrations", **{"dev-url": "sqlite://dev"}
        )
        self.assertEqual(
            run_in_layout(self, LAYOUT, migration_safety, atlas), Result.passed(CHECKED.format("atlas migrate lint"))
        )

    def test_a_project_without_migrations_is_not_judged(self) -> None:
        # A dbt project has models, not migrations: nothing to check, whatever CI runs.
        for files in (_ci("dbt build"), _ci("dbt build", "squawk models/*.sql")):
            with self.subTest(files=files):
                result = run_in_layout(self, "dbt project", migration_safety, files)
                self.assertEqual(result, Result.skipped("no migrations to judge"))
        with temp_project({"src/main.py": "", **_ci("squawk schema.sql")}) as root:
            self.assertEqual(
                run_check(migration_safety, make_context(root)), Result.skipped("not applicable to Python")
            )

    def test_several_migrations_are_counted(self) -> None:
        files = {
            "migrations/V2__amounts.sql": "alter table orders add column amount integer;\n",
            **_ci("squawk migrations/*.sql"),
        }
        result = run_in_layout(self, LAYOUT, migration_safety, files)
        self.assertEqual(result, Result.passed("CI checks the 2 migration files for unsafe changes with squawk"))

    def test_what_could_not_be_read_makes_the_answer_unknown(self) -> None:
        def answer(**fields: object) -> ToolAnswer:
            return ToolAnswer(aspect=MIGRATIONS, language="SQL", level=LINTED, **fields)  # type: ignore[arg-type]

        # Whether there are migrations, when a source could not be read; whether CI checks them, when CI could not be.
        unread = answer(answer=Answer.NO, unknown_definitions=("db/: not read",))
        self.assertEqual(judge_migration_safety(unread).status, Status.ERROR)
        self.assertEqual(judge_migration_safety(unread, allow_unknown=True), Result.skipped("no migrations to judge"))
        unknown = answer(
            answer=Answer.UNKNOWN, defined=(("squawk", ("migrations/V1__orders.sql",)),), unknowns=("ci.yml",)
        )
        self.assertEqual(judge_migration_safety(unknown).status, Status.ERROR)
        self.assertEqual(judge_migration_safety(unknown, allow_unknown=True).status, Status.WARN)
