"""SQL: dbt projects, migrations and database tests, judged by the tools CI runs on the SQL: sqlfluff (and sqlfmt) for
formatting and linting, squawk, sqlc and dbt's parser for analysis, dbt test and pgTAP for tests, dbt's packages for
dependencies, and squawk, `atlas migrate lint` or `liquibase checks run` for the safety of the migrations
(`migration-safety`: a lock held on a busy table, a column dropped), asked of a project that has migrations.

Nearly every service has a schema.sql or a migrations directory, so `.sql` alone is no ecosystem: it counts once the
project shows it works in SQL (`sql_project`): a dbt project, SQL tooling configured (sqlfluff, sqlfmt, sqlc), a
migration tool (Flyway, Liquibase, Atlas, a migrations directory of .sql files) or SQL tests (pgTAP). A stray
schema.sql in a Python project stays what it is.

dbt is the one build system: its project is a unit, its target/, dbt_packages/ and logs/ are outputs, and its packages
are dependencies locked by package-lock.yml. The platforms are the database engine versions CI tests against (the
service containers it runs: `postgres:16`, `mysql:8`), whatever the OS; the compiled-language checks do not apply.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from project_validator import yaml_support
from project_validator.core import Project
from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands
from project_validator.facts import Fact, Origin
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.axes import ToolchainAxis
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.jobs import Job
from project_validator.facts.migrations import is_migration, migration_linter, migrations_linted
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.settings import SettingsReader, ini_settings, toml_settings, unreadable
from project_validator.facts.testing import TestFile, TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import combined, defined_by, either, starts, when

SQL = "SQL"
SQL_LANGUAGE = frozenset({SQL})

# --- dbt

DBT_PROJECT = "dbt_project.yml"
DBT = BuildSystem(name="dbt", files=(DBT_PROJECT,), languages=SQL_LANGUAGE)


def _dbt_output(name: str, what: str) -> BuildOutput:
    return BuildOutput(
        languages=SQL_LANGUAGE,
        name=f"dbt's {name} directory",
        build_systems=frozenset({DBT.name}),
        globs=ignored_at_top_level(name),
        paths=directories(name),
        hint=f"ignore {name}/, {what}",
        artifacts=(f"/{name}/",),
    )


DBT_OUTPUTS = (
    _dbt_output("target", "where dbt compiles and writes its artifacts"),
    _dbt_output("dbt_packages", "where dbt deps installs the packages"),
    _dbt_output("logs", "where every dbt command logs"),
)

# --- sqlfluff: formats and lints, from one configuration

SQLFLUFF = "sqlfluff"


def _sqlfluff_section(section: str) -> str | None:
    """`[sqlfluff]` holds the top-level settings, `[sqlfluff:rules:...]` the rules'; other sections are not its."""
    if section == SQLFLUFF:
        return ""
    return section.removeprefix(f"{SQLFLUFF}:").replace(":", ".") + "." if section.startswith(f"{SQLFLUFF}:") else None


def _read_sqlfluff(path: str, text: str) -> Iterator[Fact]:
    if path.endswith("pyproject.toml"):
        return toml_settings(SQLFLUFF, path, text, "tool", SQLFLUFF)
    return ini_settings(SQLFLUFF, path, text, _sqlfluff_section)


SQLFLUFF_SETTINGS = SettingsReader(
    name=SQLFLUFF, files=(".sqlfluff", "pyproject.toml", "setup.cfg", "tox.ini"), read=_read_sqlfluff
)
# Where the project configures sqlfluff: its own file, or a `[tool.sqlfluff]` (`[sqlfluff]`) table in a shared one.
_SQLFLUFF_CONFIGURATION = defined_by(named=(".sqlfluff",), settings=(SQLFLUFF,))

# `sqlfluff lint` fails on what its rules, the layout rules included, would change; `fix` and `format` rewrite the
# files. The pre-commit hooks are `sqlfluff-lint` and `sqlfluff-fix`.
SQLFLUFF_TOOL = combined(
    format_tool(
        name=SQLFLUFF,
        languages=SQL_LANGUAGE,
        can={Enforcement.CHECK: "sqlfluff lint .", Enforcement.APPLY: "sqlfluff fix ."},
        formats=either(
            flagged(("sqlfluff", "lint"), ("sqlfluff-lint",), applies=()),
            flagged(("sqlfluff", "fix"), ("sqlfluff", "format"), ("sqlfluff-fix",), checks=()),
        ),
        style=_SQLFLUFF_CONFIGURATION,
        reads=(SQLFLUFF,),
    ),
    analyzer(
        name=SQLFLUFF,
        languages=SQL_LANGUAGE,
        how="sqlfluff lint (dialect and rules in .sqlfluff or [tool.sqlfluff])",
        analyses=when(starts(("sqlfluff", "lint"), ("sqlfluff-lint",)), analysed),
        rules=_SQLFLUFF_CONFIGURATION,
        reads=(SQLFLUFF,),
    ),
)
# sqlfmt formats dbt-style SQL; `--check` (or `--diff`) fails on a file it would change.
SQLFMT = format_tool(
    name="sqlfmt",
    languages=SQL_LANGUAGE,
    can={Enforcement.CHECK: "sqlfmt --check .", Enforcement.APPLY: "sqlfmt ."},
    formats=flagged(("sqlfmt",), checks=("--check", "--diff")),
    style=defined_by(named=(".sqlfmt.toml",)),
)

# --- analysis

# squawk lints Postgres migrations for locking and destructive changes: an analysis of the SQL, and the check of the
# migrations' safety. npm's package is squawk-cli.
_SQUAWK = starts(("squawk",), ("squawk-cli",))
SQUAWK = combined(
    analyzer(name="squawk", languages=SQL_LANGUAGE, how="squawk migrations/*.sql", analyses=when(_SQUAWK, analysed)),
    migration_linter(
        name="squawk",
        languages=SQL_LANGUAGE,
        how="squawk migrations/*.sql (or sbdchd/squawk-action with fail-on-violations: true)",
        checks=when(_SQUAWK, migrations_linted),
    ),
)
# atlas migrate lint analyses the migrations a change adds against a dev database; liquibase checks run runs the
# policy checks of a changelog.
ATLAS_LINT = migration_linter(
    name="atlas migrate lint",
    languages=SQL_LANGUAGE,
    how="atlas migrate lint --dir file://migrations --dev-url <dev database> (or ariga/atlas-action/migrate/lint)",
    checks=when(starts(("atlas", "migrate", "lint")), migrations_linted),
)
LIQUIBASE_CHECKS = migration_linter(
    name="liquibase checks",
    languages=SQL_LANGUAGE,
    how="liquibase checks run --changelog-file <changelog>",
    checks=when(starts(("liquibase", "checks", "run")), migrations_linted),
)


def _squawk_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`sbdchd/squawk-action` runs squawk on the files its `pattern` (or `files`) names, and fails the job only when
    `fail-on-violations` is true: by default it comments on the pull request."""
    if inputs.get("fail-on-violations", "false").strip().lower() != "true":
        return ()
    targets = inputs.get("files", "").split() or [inputs.get("pattern", "migrations/*.sql")]
    return (("squawk", *targets),)


SQUAWK_ACTION = Action(name="sbdchd/squawk-action", runs=_squawk_action)
ATLAS_LINT_ACTION = Action(
    name="ariga/atlas-action/migrate/lint",
    runs=lambda inputs: (("atlas", "migrate", "lint", "--dir", inputs.get("dir", "file://migrations")),),
)

ANALYZERS = (
    analyzer(name="sqlc vet", languages=SQL_LANGUAGE, how="sqlc vet", analyses=when(starts(("sqlc", "vet")), analysed)),
    analyzer(name="tsqllint", languages=SQL_LANGUAGE, how="tsqllint .", analyses=when(starts(("tsqllint",)), analysed)),
    # dbt parse (and compile) resolve every ref, source and macro, and read the project's YAML.
    analyzer(
        name="dbt parse",
        languages=SQL_LANGUAGE,
        how="dbt parse",
        analyses=when(starts(("dbt", "parse"), ("dbt", "compile")), analysed),
    ),
)

# --- tests

_DBT_TEST_KEYS = frozenset({"tests", "data_tests", "unit_tests"})
DBT_SCHEMA_TESTS = "dbt schema tests (tests: in the models' YAML)"


def _declares_tests(value: object) -> bool:
    if isinstance(value, Mapping):
        return any((key in _DBT_TEST_KEYS and found) or _declares_tests(found) for key, found in value.items())
    return isinstance(value, list) and any(_declares_tests(item) for item in value)


def _read_dbt_tests(path: str, text: str) -> Iterator[Fact]:
    """A dbt YAML file that declares tests of its models, sources, seeds or snapshots is a test file."""
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        yield unreadable("dbt", path, error)
        return
    if _declares_tests(document):
        yield TestFile(origin=Origin(path=path), language=SQL, kind=DBT_SCHEMA_TESTS)


DBT_SCHEMA_TEST_FILES = SettingsReader(
    name="dbt schema tests",
    files=tuple(
        f"{directory}/*.{suffix}" for directory in ("models", "seeds", "snapshots") for suffix in ("yml", "yaml")
    ),
    read=_read_dbt_tests,
)
# A singular test is a query under tests/ selecting the rows that must not exist, written against refs or sources.
DBT_SINGULAR_TESTS = TestFiles(
    name="dbt singular tests (tests/*.sql)",
    languages=SQL_LANGUAGE,
    path=re.compile(r"(?:^|/)tests/(?:.*/)?[^/]+\.sql$"),
    contains=re.compile(r"\{\{\s*(?:ref|source)\s*\("),
)
DBT_TEST = test_runner(
    name="dbt test",
    languages=SQL_LANGUAGE,
    how="dbt test (dbt build runs the tests too)",
    runs=when(starts(("dbt", "test"), ("dbt", "build")), tested),
    tests=tests_of(DBT_SCHEMA_TESTS, DBT_SINGULAR_TESTS.name),
    # A models' YAML file that does not parse may declare tests: the answer is unknown.
    reads=("dbt",),
)
PGTAP_TESTS = TestFiles(
    name="pgTAP tests (SELECT plan(...) in tests/*.sql)",
    languages=SQL_LANGUAGE,
    path=re.compile(r"(?:^|/)tests?/(?:.*/)?[^/]+\.sql$"),
    contains=re.compile(r"\bSELECT\s+plan\s*\(", re.IGNORECASE),
)
PG_PROVE = test_runner(
    name="pg_prove",
    languages=SQL_LANGUAGE,
    how="pg_prove tests/*.sql",
    runs=when(starts(("pg_prove",)), tested),
    tests=tests_of(PGTAP_TESTS.name),
)

# --- dependencies: dbt packages

DBT_PACKAGES = "dbt packages"
_DECLARES_PACKAGES = re.compile(r"^\s*packages\s*:", re.MULTILINE)
DBT_PACKAGE_FILES = manifest_reader(
    name="dbt package requirements",
    manager=DBT_PACKAGES,
    files=("packages.yml", "dependencies.yml"),
    declares=lambda _path, text: bool(_DECLARES_PACKAGES.search(text)),
)
DBT_PACKAGE_LOCK = lockfile_reader(manager=DBT_PACKAGES, files=("package-lock.yml",))
DBT_PACKAGES_MANAGER = PackageManager(
    name=DBT_PACKAGES,
    languages=SQL_LANGUAGE,
    lock_hint="commit package-lock.yml, which dbt deps writes (dbt 1.7+) with the version of every package",
)

# --- recognition

_TOOL_FILES = (
    ".sqlfluff",
    ".sqlfmt.toml",
    "sqlc.yaml",
    "sqlc.yml",
    "sqlc.json",
    "flyway.conf",
    "flyway.toml",
    "liquibase.properties",
    "atlas.hcl",
)
# A `[tool.sqlfluff]` table in pyproject.toml, or a `[sqlfluff]` section in setup.cfg or tox.ini.
_SHARED_CONFIGURATION = {"pyproject.toml": "[tool.sqlfluff", "setup.cfg": "[sqlfluff", "tox.ini": "[sqlfluff"}


def _tooling_configured(project: Project) -> bool:
    """A SQL tool's own configuration file, or its table in a shared one."""
    if any(project.exists(name) for name in _TOOL_FILES):
        return True
    return any(
        project.exists(path) and marker in project.read_text(path) for path, marker in _SHARED_CONFIGURATION.items()
    )


def _has_migrations(sql: list[str]) -> bool:
    return any(is_migration(path) for path in sql)


def _has_pgtap_tests(project: Project, sql: list[str]) -> bool:
    tests = (path for path in sql if PGTAP_TESTS.path.search(path))
    return PGTAP_TESTS.contains is not None and any(
        PGTAP_TESTS.contains.search(project.read_head(path)) for path in tests
    )


def sql_project(project: Project) -> frozenset[str]:
    """Whether the project works in SQL: SQL tooling configured, a migration tool or a migrations directory, or SQL
    tests. A dbt project is recognised by its build file before this is asked."""
    if _tooling_configured(project):
        return SQL_LANGUAGE
    sql = [path for path in project.files() if path.endswith(".sql")]
    return SQL_LANGUAGE if _has_migrations(sql) or _has_pgtap_tests(project, sql) else frozenset()


# What shows a CI job works on the SQL.
# The programs a CI job runs SQL with: dbt, the linters and formatters, the test runner, the migration tools.
CI_PROGRAMS = (
    *subcommands("dbt", "build", "test", "run", "compile", "parse", "deps", "seed"),
    ("sqlfluff",),
    ("sqlfmt",),
    ("pg_prove",),
    ("flyway",),
    ("liquibase",),
    ("atlas", "migrate"),
    ("sqlc",),
    ("squawk",),
    ("squawk-cli",),
    ("tsqllint",),
)

# --- platforms: the database engines CI tests against

# Image name (the registry path, without a tag) -> the engine; the tag's leading version is the engine's.
_ENGINES = {
    "postgres": "PostgreSQL",
    "postgis/postgis": "PostgreSQL",
    "timescale/timescaledb": "TimescaleDB",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mcr.microsoft.com/mssql/server": "SQL Server",
    "cockroachdb/cockroach": "CockroachDB",
    "clickhouse/clickhouse-server": "ClickHouse",
    "clickhouse": "ClickHouse",
}
_IMAGE = re.compile(r"^(?:docker\.io/)?(?:library/)?(?P<name>[\w./-]+?)(?::(?P<tag>[\w.-]+))?$")
_TAG_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")


def engine_version(image: str) -> str | None:
    """The database engine and version an image runs (`postgres:16` is "PostgreSQL 16", `mysql:8.4` "MySQL 8.4",
    `mcr.microsoft.com/mssql/server:2022-latest` "SQL Server 2022"); None for an image of no known engine, and the
    engine alone for one without a version in its tag (`postgres:latest`)."""
    match = _IMAGE.match(image.strip())
    if match is None or (engine := _ENGINES.get(match["name"])) is None:
        return None
    version = _TAG_VERSION.match(match["tag"] or "")
    return f"{engine} {version[1]}" if version else engine


def _engines(job: Job) -> frozenset[str]:
    return frozenset(engine for image in job.services if (engine := engine_version(image)) is not None)


ENGINE_VERSIONS = ToolchainAxis(
    languages=SQL_LANGUAGE, noun="database engine version", of_job=_engines, operating_systems=False
)

SQL_ECOSYSTEM = Ecosystem(
    label=SQL,
    languages=SQL_LANGUAGE,
    build_systems=(DBT,),
    ambiguous_suffixes={".sql": SQL},
    detect=sql_project,
    ci_programs=CI_PROGRAMS,
    ci_usage=re.compile(r"(?<![\w-])(?:sbdchd/squawk-action|ariga/atlas-action)\b"),
)
