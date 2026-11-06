"""Kinds of PHP project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Composer PHP",
        files={"composer.json": "{}\n", "src/App.php": ""},
        languages=frozenset({"PHP"}),
        build_systems=frozenset({"Composer"}),
    ),
)
