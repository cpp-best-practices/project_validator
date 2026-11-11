"""Code security scanners of many languages at once: CodeQL, GitLab SAST and semgrep. Each profile makes them its own,
for its languages (`multi_language_scanners`)."""

from __future__ import annotations

import re
import shlex

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.tools import Run, Tool, starts, when

# A GitLab template include is the jobs of the template, run as a marker command (see `project_validator.ci.gitlab`).
GITLAB_TEMPLATE = "gitlab-template"


_SAST_TEMPLATE = re.compile(r"(?:^|/)SAST(?:\.latest)?\.gitlab-ci\.yml")


def _gitlab_sast(command: Command, _facts: Facts) -> Run | None:
    """GitLab's SAST template (`Security/SAST.gitlab-ci.yml`, `Jobs/SAST.latest.gitlab-ci.yml`)."""
    argv = resolved(command)
    return scanned() if argv[:1] == (GITLAB_TEMPLATE,) and any(map(_SAST_TEMPLATE.search, argv)) else None


def multi_language_scanners(languages: frozenset[str]) -> tuple[Tool, ...]:
    """CodeQL, GitLab SAST and semgrep, as code security scanners of `languages`."""
    return (
        scanner(
            name="CodeQL",
            languages=languages,
            how="CodeQL (github/codeql-action)",
            scans=when(starts(("codeql", "database", "analyze")), scanned),
        ),
        scanner(
            name="GitLab SAST", languages=languages, how="GitLab SAST (Security/SAST.gitlab-ci.yml)", scans=_gitlab_sast
        ),
        scanner(
            name="semgrep",
            languages=languages,
            how="semgrep ci",
            scans=when(starts(("semgrep", "ci"), ("semgrep", "scan"), ("semgrep", "--config")), scanned),
        ),
    )


CODEQL_ACTION = Action(name="github/codeql-action/analyze", runs=lambda _inputs: (("codeql", "database", "analyze"),))
SEMGREP_ACTIONS = tuple(
    Action(name=name, runs=lambda inputs: (("semgrep", "ci", *shlex.split(inputs.get("config", ""))),))
    for name in ("returntocorp/semgrep-action", "semgrep/semgrep-action")
)
