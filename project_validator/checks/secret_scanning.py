"""Secrets committed by mistake are caught: CI, or a pre-commit hook, runs a secret scanner."""

from project_validator.core import Context, Result, check
from project_validator.facts.practices import named
from project_validator.text import pattern

SECRET_SCANNERS = (
    pattern("gitleaks", r"\bgitleaks\b"),
    pattern("TruffleHog", r"\btrufflehog\b"),
    pattern("detect-secrets", r"\bdetect-secrets(?:-hook)?\b"),
    pattern("ggshield", r"\bggshield\b"),
    pattern("Nosey Parker", r"\bnoseyparker\b|\bnosey-parker\b"),
)
# Configuration files that show a scanner is meant to run: scanner name -> its files.
SCANNER_CONFIGURATION = {
    "gitleaks": (".gitleaks.toml", ".gitleaksignore"),
    "detect-secrets": (".secrets.baseline",),
    "ggshield": (".gitguardian.yaml", ".gitguardian.yml"),
}
HINT = (
    "consider running gitleaks, TruffleHog (trufflesecurity/trufflehog) or detect-secrets in CI or as a pre-commit "
    "hook; GitHub's secret scanning and push protection are repository settings, which cannot be seen from here"
)


@check(name="secret-scanning", description="CI scans for committed secrets (e.g. gitleaks, TruffleHog)")
def secret_scanning(context: Context) -> Result:
    if scanners := named(context.facts, SECRET_SCANNERS):
        return Result.passed(f"secrets are scanned for with {', '.join(scanners)}")
    configured = [name for name, files in SCANNER_CONFIGURATION.items() if any(map(context.project.exists, files))]
    if configured:
        verb = "is" if len(configured) == 1 else "are"
        runs = "runs it" if len(configured) == 1 else "runs them"
        return Result.warned(
            f"{', '.join(configured)} {verb} configured, but neither CI nor a pre-commit hook {runs}", HINT
        )
    return Result.warned("no secret scanning found in CI configuration", HINT)
