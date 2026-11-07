"""The dependency audit aspect of tools (see `project_validator.facts.tools`): a run checks the project's dependencies
against known vulnerabilities. Auditors are ordinary `Tool`s; `auditor` and `audited` only spell them."""

from collections.abc import Iterable

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Run, Tool, provided

AUDIT = "audit"
RUNS = "runs"


def auditor(*, name: str, languages: frozenset[str], how: str, audits: Claim, reads: tuple[str, ...] = ()) -> Tool:
    """A dependency auditor of `languages`: `how` to run it."""
    return Tool(name=name, languages=languages, can={AUDIT: {RUNS: how}}, claims=audits, reads=reads)


def audited(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(AUDIT, RUNS, read=read, heuristic=heuristic)


__all__ = ["AUDIT", "RUNS", "audited", "auditor"]
