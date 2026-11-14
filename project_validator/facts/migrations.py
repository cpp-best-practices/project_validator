"""The migration aspect of tools (see `project_validator.facts.tools`): a run checks a project's database migrations
for changes that are unsafe to apply to a live database, and fails on one (`migrations`: squawk on Postgres migrations,
for locking and destructive statements; `atlas migrate lint`; `liquibase checks run`). A migration linter's definitions
are the migrations themselves: Flyway-named files (`V1__init.sql`, `R__view.sql`) and the `.sql` files of a
`migrations/`, `db/migrate/` or `db/migrations/` directory, the files the SQL profile recognises a migrations project
by. All are ordinary `Tool`s; `migration_linter` and `migrations_linted` only spell them."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from project_validator.facts import Facts, Setting
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

MIGRATIONS = "migrations"
LINTED = "linted"

# Flyway's versioned, undo and repeatable migrations: V1__init.sql, V2_1__add_index.sql, R__view.sql.
FLYWAY_MIGRATION = re.compile(r"(?:^|/)(?:[VU]\d[\w.]*|R)__[^/]*\.sql$")
MIGRATIONS_DIRECTORY = re.compile(r"(?:^|/)(?:migrations|db/migrate|db/migrations)/[^/]+\.sql$")
DESCRIBED = "migrations (V1__init.sql, or .sql files under migrations/, db/migrate/ or db/migrations/)"


def is_migration(path: str) -> bool:
    """Whether a path is a database migration's, by its name or its directory."""
    return FLYWAY_MIGRATION.search(path) is not None or MIGRATIONS_DIRECTORY.search(path) is not None


def migration_files(facts: Facts) -> Iterator[str]:
    """The paths of the project's SQL migrations."""
    from project_validator.facts.structure import SourceFile  # structure reads the profiles, which define linters

    return (source.path for source in facts.of(SourceFile) if source.language == "SQL" and is_migration(source.path))


MIGRATION_DEFINITION = Definition(found=migration_files, default=False, describe=DESCRIBED)


def migration_linter(
    *, name: str, languages: frozenset[str], how: str, checks: Claim, reads: tuple[str, ...] = ()
) -> Tool:
    """A linter of the migrations of `languages` for unsafe changes: `how` to run it. The migrations are what it
    checks, so a project without them has nothing to ask."""
    return Tool(
        name=name,
        languages=languages,
        can={MIGRATIONS: {LINTED: how}},
        claims=checks,
        reads=reads,
        definitions={MIGRATIONS: MIGRATION_DEFINITION},
    )


def migrations_linted(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(MIGRATIONS, LINTED, read=read, heuristic=heuristic)


__all__ = [
    "DESCRIBED",
    "FLYWAY_MIGRATION",
    "LINTED",
    "MIGRATIONS",
    "MIGRATIONS_DIRECTORY",
    "is_migration",
    "migration_files",
    "migration_linter",
    "migrations_linted",
]
