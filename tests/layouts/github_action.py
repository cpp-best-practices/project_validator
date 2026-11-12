"""Kinds of GitHub Action repository, for tests that run a check in every layout: a composite action."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

ACTION = """\
name: Shop total
description: Sums the prices given.
inputs:
  prices:
    description: The prices, separated by spaces.
    required: true
outputs:
  total:
    description: Their sum.
    value: ${{ steps.sum.outputs.total }}
runs:
  using: composite
  steps:
    - id: sum
      shell: bash
      run: |
        total=0
        for price in ${{ inputs.prices }}; do total=$((total + price)); done
        echo "total=$total" >> "$GITHUB_OUTPUT"
"""

LAYOUTS = (
    ProjectLayout(
        name="GitHub Action",
        files={"action.yml": ACTION},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"GitHub Action", "YAML"}),
    ),
)
