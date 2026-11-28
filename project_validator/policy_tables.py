"""The policy tables (upstream #440): the judgement calls behind the score and the unknowns, kept as TOML files in
`project_validator/policy/`, beside the policies that judge the answers, so that they can be read, reviewed and
changed apart from the code, which only loads and applies them.

- `strength.toml`: what a turned-off diagnostic and a suppression cost a tool's strength (see `strength`).
- `diagnostics.toml`: each tool's diagnostics that turn everything off, and those that find bugs, with what some of
  them guard against (see `facts.suppressions.Disabler`).
- `score.toml`: the levels, the slots' weights, the extra credit and the checks that are never scored (see `score`).
- `inert_actions.toml`: the GitHub Actions known to run none of the project's code (see `ci.inert_actions`).

The tables are the validator's, not a project's: a project cannot override them, since that would let it change its
own score. Changing a number in a scored table (`SCORED`) changes the score, so it bumps `score.SCORE_VERSION`; a test
ties the two together through `digest`."""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from typing import Any

TABLES = ("diagnostics", "inert_actions", "score", "strength")
# The tables whose numbers decide the score.
SCORED = ("diagnostics", "score", "strength")


def _text(name: str) -> str:
    if name not in TABLES:
        raise KeyError(f"no policy table {name!r}: one of {', '.join(TABLES)}")
    # Read from the package's folder without importing the policies, which import most of the validator.
    return (files("project_validator") / "policy" / f"{name}.toml").read_text(encoding="utf-8")


@cache
def load(name: str) -> Mapping[str, Any]:
    """The table `name` (one of `TABLES`), read once."""
    return tomllib.loads(_text(name))


def digest_text(text: str) -> str:
    """A digest of a table's text that a checkout's line endings do not change."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()[:16]


def digest(*names: str) -> str:
    """One digest of the tables `names`, in that order."""
    return digest_text("".join(_text(name) for name in names))


__all__ = ["SCORED", "TABLES", "digest", "digest_text", "load"]
