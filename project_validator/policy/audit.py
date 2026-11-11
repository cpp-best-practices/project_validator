"""The dependency audit policy: CI checks the dependencies against known vulnerabilities. An audit passes; none warns
(dependencies change under a project, so this is advice more than a defect)."""

from __future__ import annotations

from project_validator.facts.audit import RUNS
from project_validator.policy.tooling import advised

judge_audit = advised(
    level=RUNS,
    impossible="no known tool audits the dependencies of {language}",
    passed="CI audits the dependencies with {tools}",
    asks="whether CI audits the dependencies",
    missing="no dependency vulnerability audit found in CI configuration",
)

__all__ = ["judge_audit"]
