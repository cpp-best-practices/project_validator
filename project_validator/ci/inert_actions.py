"""The GitHub Actions known to run none of the project's code (upstream #273): the curated list, kept in
`project_validator/policy/inert_actions.toml` (upstream #440), which says how to add one.

A job whose only work is an action of another repository that the validator does not read may run any tool, so what it
runs is unknown (an error under --strict) until --fetch-remote reads its action.yml. The actions listed run none of
the project's code or tools, so their jobs are known to run nothing the checks look for."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator import policy_tables


@dataclass(frozen=True, slots=True)
class InertGroup:
    """Actions that run none of the project's code, and what they do instead."""

    does: str
    actions: tuple[str, ...]


_TABLE = policy_tables.load("inert_actions")
# The owners of GitHub's own actions (checkout, caches, artifacts, Pages, CodeQL).
OFFICIAL_OWNERS = tuple(_TABLE["official_owners"])
INERT_ACTIONS = tuple(InertGroup(group["does"], tuple(group["actions"])) for group in _TABLE["groups"])


def inert(repository: str) -> bool:
    """Whether the action of `repository` (`owner/repo[/path]`, without its `@ref`) is known to run none of the
    project's code: one of GitHub's own, or one listed (or under a listed path)."""
    name = repository.lower()
    if name.startswith(OFFICIAL_OWNERS):
        return True
    return any(name == listed or name.startswith(f"{listed}/") for group in INERT_ACTIONS for listed in group.actions)


__all__ = ["INERT_ACTIONS", "OFFICIAL_OWNERS", "InertGroup", "inert"]
