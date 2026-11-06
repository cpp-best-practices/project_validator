"""Kinds of .NET project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="MSBuild C#",
        files={"src/App/App.csproj": "<Project/>\n", "src/App/Program.cs": ""},
        languages=frozenset({"C#"}),
        build_systems=frozenset({"MSBuild"}),
    ),
    ProjectLayout(
        name="MSBuild F#",
        files={"App.fsproj": "<Project/>\n", "Program.fs": ""},
        languages=frozenset({"F#"}),
        build_systems=frozenset({"MSBuild"}),
        # No known tool limits the length of F# functions.
        skipped=frozenset({"function-limits"}),
    ),
)
