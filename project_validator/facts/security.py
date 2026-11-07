"""The code security scanning aspect of tools (see `project_validator.facts.tools`): a run looks for security problems
in the project's code, a multi-language scanner (CodeQL) or a language's security lints (bandit, gosec). Scanners are
ordinary `Tool`s; `scanner` and `scanned` only spell them."""

from collections.abc import Iterable

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Run, Tool, provided

SECURITY = "security"
SCANS = "scans"


def scanner(*, name: str, languages: frozenset[str], how: str, scans: Claim, reads: tuple[str, ...] = ()) -> Tool:
    """A code security scanner, or a security lint, of `languages`: `how` to run it."""
    return Tool(name=name, languages=languages, can={SECURITY: {SCANS: how}}, claims=scans, reads=reads)


def scanned(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(SECURITY, SCANS, read=read, heuristic=heuristic)


__all__ = ["SCANS", "SECURITY", "scanned", "scanner"]
