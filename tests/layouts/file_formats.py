"""Kinds of project holding files of the file formats, for tests that run a check in every layout: an icon, a table
and settings beside nothing else."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="File formats",
        files={
            "assets/icon.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n',
            "data/table.csv": "name,count\napple,3\n",
            "tox.ini": "[tox]\nenvlist = py314\n",
        },
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"CSV", "INI", "SVG"}),
    ),
)
