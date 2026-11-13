"""Kinds of Jupyter project, for tests that run a check in every layout: notebooks and nothing else."""

from __future__ import annotations

import json

from tests.layouts.model import ProjectLayout


def notebook(*sources: str) -> str:
    """A notebook of code cells with `sources`, without outputs, as Jupyter writes one."""
    cells: list[dict[str, object]] = [
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source}
        for source in sources
    ]
    metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}
    return json.dumps({"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 5}, indent=1) + "\n"


PRICES = notebook("prices = [1, 2, 3]\n", "total = sum(prices)\nassert total == 6\n")

LAYOUTS = (
    ProjectLayout(
        name="Jupyter notebooks",
        files={"notebooks/prices.ipynb": PRICES},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Jupyter"}),
    ),
)
