# SQL

Recognised by intent, not by `.sql` files alone: nearly every service has a `schema.sql` or a migrations directory,
which stay invisible (a stray `schema.sql` in a Python project adds no SQL column). `.sql` files count once the project
shows it works in SQL: a dbt project (`dbt_project.yml`, its one build system); SQL tooling configured (`.sqlfluff` or a
`[tool.sqlfluff]` table in `pyproject.toml`, `.sqlfmt.toml`, `sqlc.yaml`); a migration tool (`flyway.conf`,
`liquibase.properties`, `atlas.hcl`, Flyway-named `V1__init.sql` files, or a `migrations/`, `db/migrate/` or
`db/migrations/` directory of `.sql` files); or pgTAP tests (`SELECT plan(...)` under `tests/`).

The compiled-language checks (coverage, compiler warnings, hardening, build types, fuzzing, mutation testing) do not
apply, and nor do `security-scanning` (no SQL scanner is known) and `function-limits`.

## `code-formatting`

`sqlfluff lint`, whose layout rules fail on a file it would reformat (`sqlfluff fix` and `sqlfluff format` rewrite
them), or `sqlfmt --check` (plain `sqlfmt` rewrites); the pre-commit hooks `sqlfluff-lint`, `sqlfluff-fix` and `sqlfmt`.
Both have a default style, so running one is enough.

## `static-analysis`

`sqlfluff lint`, with its dialect and rules in `.sqlfluff` or `[tool.sqlfluff]` (`[sqlfluff]` in `setup.cfg` or
`tox.ini`); squawk, which lints Postgres migrations for locking and destructive changes (and is `migration-safety`'s check); `sqlc vet`; tsqllint; or
`dbt parse` (or `dbt compile`), which resolves every ref, source and macro.

## `tests-run`

`dbt test`, or `dbt build`, which runs the tests too, with tests to run: schema tests (`tests:`, `data_tests:` or
`unit_tests:` in the YAML under `models/`, `seeds/` or `snapshots/`) or singular tests (`tests/*.sql` selecting from a
`ref()` or `source()`). pgTAP tests (`tests/*.sql` with `SELECT plan(...)`) run by `pg_prove`. A test needs a database,
which CI provides as a service container or an installation; that is not checked for.

## `migration-safety`

A project with migrations (Flyway-named files, or `.sql` files under `migrations/`, `db/migrate/` or `db/migrations/`)
has CI check them for changes that are unsafe to apply to a live database: squawk (`squawk migrations/*.sql`, npm's
`squawk-cli`; or `sbdchd/squawk-action`, which fails the job only with `fail-on-violations: true`, as by default it
comments on the pull request), `atlas migrate lint` (or `ariga/atlas-action/migrate/lint`), or `liquibase checks run`.
Warns when CI checks nothing. A dbt project or plain SQL without migrations has nothing to judge, and the check is
skipped. squawk is an analysis of the SQL too (`static-analysis`).

## `dependency-management`

dbt packages: `packages.yml` (or `dependencies.yml`) declares them, and `dbt deps` locks their versions in
`package-lock.yml` (dbt 1.7+), which must be committed. Migrations and plain SQL have no dependencies to manage.

## `committed-artifacts`

A committed `target/`, `dbt_packages/` or `logs/` directory of a dbt project fails. Other SQL projects have no known
output, so the check does not apply to them.

## `vcs-ignore`

A dbt project's ignore rules keep out `target/`, `dbt_packages/` and `logs/`.

## `platform-matrix`

Does not apply. The toolchains of a database project are database engine versions (the `postgres:16` and `mysql:8`
service containers CI runs), and the platform policy asks for several operating systems too, which SQL has no use
for. A policy of engine versions alone is a change to the check, not to this profile.
