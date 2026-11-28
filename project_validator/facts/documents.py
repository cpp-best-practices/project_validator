"""The documents a project keeps for its contributors and users (upstream #412): its changelog and its latest entry,
CONTRIBUTING, CODEOWNERS, issue and pull request templates, and a Doxygen configuration. Shown, never judged; read by
`project_validator.tools.documents`."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator.facts import Fact

CHANGELOG, CONTRIBUTING, CODEOWNERS = "changelog", "contributing", "codeowners"
ISSUE_TEMPLATE, PULL_REQUEST_TEMPLATE, DOXYGEN = "issue template", "pull request template", "Doxygen"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectDocument(Fact):
    """A document of `kind` (`changelog`, `contributing`…), and what it says that is shown: a changelog's latest
    version ("" when no entry names one)."""

    kind: str
    latest: str = ""


__all__ = [
    "CHANGELOG",
    "CODEOWNERS",
    "CONTRIBUTING",
    "DOXYGEN",
    "ISSUE_TEMPLATE",
    "PULL_REQUEST_TEMPLATE",
    "ProjectDocument",
]
