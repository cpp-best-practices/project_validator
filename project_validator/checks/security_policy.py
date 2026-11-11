"""Whoever finds a vulnerability knows how to report it privately."""

from __future__ import annotations

import re

from project_validator.core import Context, Result, check
from project_validator.evidence import documents

SECURITY_POLICY = re.compile(r"SECURITY(?:\.(?:md|markdown|rst|txt|adoc))?", re.IGNORECASE)
# A way to report: an email address, a link, or a forge's private vulnerability reporting.
REPORTING = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|private vulnerability report|security advisor(?:y|ies)",
    re.IGNORECASE,
)
HINT = (
    "add a SECURITY.md that says how to report a vulnerability privately: an email address, or GitHub's private "
    "vulnerability reporting (Settings > Code security, then link to /security/advisories/new)"
)


@check(name="security-policy", description="A security policy says how to report a vulnerability privately")
def security_policy(context: Context) -> Result:
    policies = documents(context, SECURITY_POLICY)
    if not policies:
        return Result.warned("no security policy", HINT)
    if reporting := [path for path in policies if REPORTING.search(context.project.read_text(path))]:
        return Result.passed(f"{reporting[0]} says how to report a vulnerability")
    return Result.warned(f"{policies[0]} does not say how to report a vulnerability", HINT)
