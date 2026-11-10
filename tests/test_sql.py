"""The SQL profile's rules, judged by the generic checks in the SQL project layouts."""

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.sql import SQL_ECOSYSTEM
from project_validator.facts import Setting
from tests.support import github_job, make_context, run_as, run_in_layout, temp_project

SQL = frozenset({"SQL"})
PYTHON_PROJECT = {
    "pyproject.toml": '[project]\nname = "app"\n',
    "app.py": "",
    "schema.sql": "create table t (id int);\n",
}
SCHEMA_TESTS = {
    "models/schema.yml": "models:\n  - name: orders\n    columns:\n      - name: id\n        tests: [unique]"
}
SINGULAR_TEST = {"tests/assert_amounts.sql": "select * from {{ ref('orders') }} where amount < 0\n"}
PGTAP_TEST = {"tests/orders.sql": "BEGIN;\nSELECT plan(1);\nSELECT has_table('orders');\nROLLBACK;\n"}
PACKAGES = {"packages.yml": "packages:\n  - package: dbt-labs/dbt_utils\n    version: 1.3.0\n"}
LOCK = {"package-lock.yml": "packages:\n  - package: dbt-labs/dbt_utils\n    version: 1.3.0\n"}
PRE_COMMIT = {
    ".pre-commit-config.yaml": (
        "repos:\n  - repo: https://github.com/sqlfluff/sqlfluff\n    rev: 3.3.0\n    hooks:\n"
        "      - id: sqlfluff-lint\n"
    )
}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _languages(files: dict[str, str]) -> frozenset[str]:
    with temp_project(files) as root:
        return make_context(root).structure.languages


class RecognitionTests(unittest.TestCase):
    def test_sql_files_alone_are_not_an_ecosystem(self) -> None:
        self.assertEqual(_languages(PYTHON_PROJECT), frozenset({"Python"}))
        with temp_project({"schema.sql": "", "backend/migrations/0001_init.py": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Python"}))
        self.assertEqual(structure.unrecognised_suffixes, ((".sql", 1),))

    def test_a_dbt_project_is_sql(self) -> None:
        with temp_project({"dbt_project.yml": "name: shop\n", "models/orders.sql": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, SQL)
        self.assertEqual(structure.build_systems, frozenset({"dbt"}))
        self.assertEqual(structure.unrecognised_suffixes, ())

    def test_configured_sql_tooling_shows_intent(self) -> None:
        for files in (
            {".sqlfluff": "[sqlfluff]\ndialect = postgres\n"},
            {"pyproject.toml": '[project]\nname = "app"\n\n[tool.sqlfluff]\ndialect = "postgres"\n'},
            {"setup.cfg": "[sqlfluff]\ndialect = postgres\n"},
            {".sqlfmt.toml": "[tool.sqlfmt]\n"},
            {"sqlc.yaml": "version: '2'\n"},
            {"flyway.conf": "flyway.locations=filesystem:migrations\n"},
            {"liquibase.properties": "changeLogFile=db/changelog.xml\n"},
            {"atlas.hcl": 'env "local" {}\n'},
        ):
            with self.subTest(files=list(files)):
                self.assertIn("SQL", _languages({**PYTHON_PROJECT, **files}))

    def test_migrations_and_sql_tests_show_intent(self) -> None:
        for path in (
            "migrations/V1__init.sql",
            "db/migrate/20240101_init.sql",
            "db/migrations/0001_init.sql",
            "sql/V2_1__add_index.sql",
            "sql/R__orders_view.sql",
        ):
            with self.subTest(path=path):
                self.assertEqual(_languages({path: "create table t (id int);\n"}), SQL)
        self.assertEqual(_languages(PGTAP_TEST), SQL)
        self.assertEqual(_languages({"tests/orders.sql": "select 1;\n"}), frozenset())
        self.assertEqual(_languages({"sql/init.sql": "", "docs/migrations.md": ""}), frozenset())


class SqlTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, SQL_ECOSYSTEM)

    def test_sqlfluff_lint_and_sqlfmt_check_enforce_the_formatting(self) -> None:
        for command in ("sqlfluff lint .", "sqlfmt --check models", "sqlfmt --diff models"):
            with self.subTest(command=command):
                self.assertEqual(self._run(code_formatting, _ci(command)).status, Status.PASS)
        for command in ("sqlfluff fix .", "sqlfluff format .", "sqlfmt models"):
            with self.subTest(command=command):
                self.assertEqual(self._run(code_formatting, _ci(command)).status, Status.FAIL)
        hooks = {**PRE_COMMIT, **_ci("pre-commit run --all-files")}
        self.assertEqual(self._run(code_formatting, hooks).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, hooks).status, Status.PASS)

    def test_sqlfluff_lints_with_the_configuration_it_finds(self) -> None:
        own = {
            ".sqlfluff": "[sqlfluff]\ndialect = postgres\n\n[sqlfluff:rules:capitalisation.keywords]\n"
            "capitalisation_policy = lower\n"
        }
        self.assertEqual(
            self._run(static_analysis, {**own, **_ci("sqlfluff lint .")}), Result.passed("sqlfluff (.sqlfluff) runs")
        )
        # A shared configuration file, in a project that is Python's too.
        shared = {
            "dbt_project.yml": "name: shop\n",
            "models/a.sql": "",
            "pyproject.toml": '[tool.sqlfluff]\ndialect = "postgres"\n',
        }
        with temp_project({**shared, **_ci("sqlfluff lint .")}) as root:
            result = static_analysis.run(make_context(root))
        self.assertIn("sqlfluff (pyproject.toml) runs", result.message)
        # Without a configuration, sqlfluff still lints, with the dialect the command names.
        result = self._run(static_analysis, _ci("sqlfluff lint --dialect postgres ."))
        self.assertEqual(result, Result.passed("sqlfluff runs"))

    def test_the_sqlfluff_settings_are_read(self) -> None:
        text = (
            "[sqlfluff]\ndialect = postgres\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = lower"
        )
        with temp_project({"dbt_project.yml": "name: shop\n", "models/a.sql": "", ".sqlfluff": text}) as root:
            found = {setting.key: setting.value for setting in make_context(root).facts.where(Setting, tool="sqlfluff")}
        self.assertEqual(found, {"dialect": "postgres", "rules.capitalisation.keywords.capitalisation_policy": "lower"})

    def test_squawk_sqlc_tsqllint_and_dbt_parse_are_analysis(self) -> None:
        for command in ("squawk migrations/*.sql", "sqlc vet", "tsqllint .", "dbt parse", "dbt compile"):
            with self.subTest(command=command):
                self.assertEqual(self._run(static_analysis, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, _ci("dbt run", "sqlc generate")).status, Status.FAIL)

    def test_dbt_test_runs_the_schema_and_singular_tests(self) -> None:
        self.assertEqual(self._run(tests_run, {**SCHEMA_TESTS, **_ci("dbt test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**SINGULAR_TEST, **_ci("dbt deps", "dbt build")}).status, Status.PASS)
        data_tests = {"models/orders.yml": "models:\n  - name: orders\n    data_tests:\n      - row_count\n"}
        self.assertEqual(self._run(tests_run, {**data_tests, **_ci("dbt test")}).status, Status.PASS)
        no_tests = {"models/schema.yml": "version: 2\nmodels:\n  - name: orders\n    description: Orders.\n"}
        self.assertEqual(self._run(tests_run, {**no_tests, **_ci("dbt test")}).status, Status.FAIL)
        plain_query = {"tests/count.sql": "select count(*) from orders\n", **_ci("dbt test")}
        self.assertEqual(self._run(tests_run, plain_query).status, Status.FAIL)
        self.assertEqual(self._run(tests_run, {**SCHEMA_TESTS, **_ci("dbt run")}).status, Status.WARN)
        # A YAML file that does not parse may hold tests: unknown.
        broken = {"models/schema.yml": "models: [", **_ci("dbt test")}
        self.assertEqual(self._run(tests_run, broken).status, Status.ERROR)

    def test_pg_prove_runs_the_pgtap_tests(self) -> None:
        self.assertEqual(self._run(tests_run, {**PGTAP_TEST, **_ci("pg_prove tests/*.sql")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, _ci("pg_prove tests/*.sql")).status, Status.FAIL)

    def test_dbt_packages_are_locked_by_the_package_lock(self) -> None:
        self.assertEqual(self._run(dependency_management, {**PACKAGES, **LOCK}).status, Status.PASS)
        result = self._run(dependency_management, PACKAGES)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("package-lock.yml", " ".join(result.details))
        self.assertEqual(
            self._run(dependency_management, {"dependencies.yml": "packages:\n  - local: ../shared\n"}).status,
            Status.WARN,
        )
        self.assertEqual(self._run(dependency_management, {}).status, Status.PASS)

    def test_a_dbt_project_ignores_what_dbt_writes(self) -> None:
        ignoring = {".gitignore": "target/\ndbt_packages/\nlogs/\n"}
        self.assertEqual(run_in_layout(self, "dbt project", vcs_ignore, ignoring).status, Status.PASS)
        result = run_in_layout(self, "dbt project", vcs_ignore, {".gitignore": "target/\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(
            run_in_layout(self, "dbt project", committed_artifacts, {"target/manifest.json": "{}"}).status, Status.FAIL
        )
        self.assertEqual(run_in_layout(self, "dbt project", committed_artifacts, {}).status, Status.PASS)

    def test_migrations_have_no_outputs(self) -> None:
        self.assertEqual(run_in_layout(self, "SQL migrations", committed_artifacts, {}).status, Status.SKIP)
        self.assertEqual(run_in_layout(self, "SQL migrations", vcs_ignore, {".gitignore": ""}).status, Status.SKIP)

    def test_ci_usage(self) -> None:
        for text in ("dbt build --profiles-dir .", "sqlfluff lint models", "pg_prove tests/*.sql", "flyway migrate"):
            with self.subTest(text=text):
                self.assertTrue(SQL_ECOSYSTEM.used_by(text))
        self.assertFalse(SQL_ECOSYSTEM.used_by("npm test"))
