"""The code security scanning policy: CI scans the code, with a multi-language scanner or the language's own security
lints. A scan passes; none warns."""

from __future__ import annotations

from project_validator.facts.security import SCANS
from project_validator.policy.tooling import advised

judge_security = advised(
    level=SCANS,
    impossible="no known tool scans {language} for security problems",
    passed="CI scans the code for security problems with {tools}",
    asks="whether CI scans the code for security problems",
    missing="no code security scanning found in CI configuration",
)

__all__ = ["judge_security"]
