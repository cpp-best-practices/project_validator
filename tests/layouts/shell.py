"""Kinds of shell project, for tests that run a check in every layout: shell scripts, and a PowerShell module."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

SCRIPT = (
    "#!/usr/bin/env bash\nset -euo pipefail\n\n"
    'total() {\n  local sum=0\n  for price in "$@"; do\n    sum=$((sum + price))\n  done\n  echo "$sum"\n}\n'
)
MODULE = "function Get-Total {\n    param([int[]]$Prices)\n    ($Prices | Measure-Object -Sum).Sum\n}\n"

LAYOUTS = (
    ProjectLayout(
        name="Shell scripts",
        files={"src/shop.sh": SCRIPT},
        languages=frozenset({"Shell"}),
        build_systems=frozenset(),
    ),
    ProjectLayout(
        name="PowerShell module",
        files={"src/Shop.psm1": MODULE},
        languages=frozenset({"PowerShell"}),
        build_systems=frozenset(),
    ),
)
