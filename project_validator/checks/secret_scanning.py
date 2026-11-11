"""Secrets committed by mistake are caught: CI, or a pre-commit hook, runs a secret scanner."""

from __future__ import annotations

from project_validator.core import Context, Result, check
from project_validator.policy.secrets import judge_secret_scanning
from project_validator.questions.secrets import secret_scanning_answer


@check(name="secret-scanning", description="CI scans for committed secrets (e.g. gitleaks, TruffleHog)")
def secret_scanning(context: Context) -> Result:
    return judge_secret_scanning(secret_scanning_answer(context.facts))
