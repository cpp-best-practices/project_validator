"""Kinds of SQL project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

SQL = frozenset({"SQL"})

LAYOUTS = (
    ProjectLayout(
        name="dbt project",
        files={
            "dbt_project.yml": 'name: shop\nversion: "1.0.0"\nprofile: shop\n',
            "models/orders.sql": "select 1 as id\n",
        },
        languages=SQL,
        build_systems=frozenset({"dbt"}),
    ),
    ProjectLayout(
        name="SQL migrations",
        files={"migrations/V1__init.sql": "create table orders (id integer primary key);\n"},
        languages=SQL,
        build_systems=frozenset(),
        # Only dbt has outputs that could be committed (vcs-ignore still asks for an ignore file).
        skipped=frozenset({"committed-artifacts"}),
    ),
)
