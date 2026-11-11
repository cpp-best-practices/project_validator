"""The secret scanning policy: CI or a pre-commit hook runs a secret scanner; one configured but not run warns."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.questions import Answer
from project_validator.questions.secrets import SecretScanningAnswer

HINT = (
    "consider running gitleaks, TruffleHog (trufflesecurity/trufflehog) or detect-secrets in CI or as a pre-commit "
    "hook; GitHub's secret scanning and push protection are repository settings, which cannot be seen from here"
)


def judge_secret_scanning(answer: SecretScanningAnswer, *, allow_unknown: bool = False) -> Result:
    """A scanner run passes; one configured but not run warns, as does none at all (advice: the forge's own scanning
    cannot be seen)."""
    del allow_unknown  # the scanners are searched for in the configuration text itself: nothing is hidden
    if answer.answer is Answer.YES:
        return Result.passed(f"secrets are scanned for with {', '.join(answer.scanners)}")
    if configured := answer.configured:
        verb, runs = ("is", "runs it") if len(configured) == 1 else ("are", "runs them")
        return Result.warned(
            f"{', '.join(configured)} {verb} configured, but neither CI nor a pre-commit hook {runs}", HINT
        )
    return Result.warned("no secret scanning found in CI configuration", HINT)


__all__ = ["HINT", "judge_secret_scanning"]
