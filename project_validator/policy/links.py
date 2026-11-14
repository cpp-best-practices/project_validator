"""The link-check policy: CI checks the documentation's links and fails on a broken one; none warns, as a broken link
misleads a reader without breaking a build, and a site may be checked on a schedule rather than on every change (a
scheduled job's run counts)."""

from __future__ import annotations

from project_validator.facts.links import CHECKED
from project_validator.policy.tooling import advised

judge_link_check = advised(
    level=CHECKED,
    impossible="no known tool checks the links of {language} documentation",
    passed="CI checks the documentation's links with {tools}",
    asks="whether CI checks the documentation's links",
    missing="no link check found in CI configuration",
)

__all__ = ["judge_link_check"]
