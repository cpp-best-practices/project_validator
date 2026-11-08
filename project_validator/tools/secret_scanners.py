"""Secret scanners, which look through a repository of any language for committed credentials: how CI or a pre-commit
hook runs each, and the configuration files that show one is meant to run."""

from project_validator.facts.settings import file_reader
from project_validator.text import pattern

SECRET_SCANNERS = (
    pattern("gitleaks", r"\bgitleaks\b"),
    pattern("TruffleHog", r"\btrufflehog\b"),
    pattern("detect-secrets", r"\bdetect-secrets(?:-hook)?\b"),
    pattern("ggshield", r"\bggshield\b"),
    pattern("Nosey Parker", r"\bnoseyparker\b|\bnosey-parker\b"),
)

# Configuration files that show a scanner is meant to run, recorded as the files a reader named after the scanner read.
GITLEAKS_FILES = file_reader("gitleaks", (".gitleaks.toml", ".gitleaksignore"))
DETECT_SECRETS_FILES = file_reader("detect-secrets", (".secrets.baseline",))
GGSHIELD_FILES = file_reader("ggshield", (".gitguardian.yaml", ".gitguardian.yml"))
CONFIGURED_SCANNERS = tuple(reader.name for reader in (GITLEAKS_FILES, DETECT_SECRETS_FILES, GGSHIELD_FILES))

__all__ = ["CONFIGURED_SCANNERS", "DETECT_SECRETS_FILES", "GGSHIELD_FILES", "GITLEAKS_FILES", "SECRET_SCANNERS"]
