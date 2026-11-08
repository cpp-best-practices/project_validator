import unittest
from collections.abc import Mapping

from project_validator.checks.secret_scanning import secret_scanning
from project_validator.core import Result, Status
from project_validator.policy.secrets import HINT
from tests.support import CI_FILES, FIXTURES, GITHUB_WORKFLOW, github_steps, make_context, temp_project


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return secret_scanning.run(make_context(root))


class SecretScanningTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(secret_scanning.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = secret_scanning.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result, Result.passed("secrets are scanned for with gitleaks"))

    def test_warns_without_a_secret_scanner(self) -> None:
        for files in ({}, {GITHUB_WORKFLOW: "jobs: {}\n"}, {"docs/gitleaks.md": "gitleaks"}):
            with self.subTest(files=list(files)):
                self.assertEqual(_run(files), Result.warned("no secret scanning found in CI configuration", HINT))

    def test_passes_with_any_secret_scanner_in_ci(self) -> None:
        scanners = {
            "gitleaks": "uses: gitleaks/gitleaks-action@v2",
            "TruffleHog": "uses: trufflesecurity/trufflehog@main",
            "detect-secrets": "run: detect-secrets-hook --baseline .secrets.baseline",
            "ggshield": "run: ggshield secret scan ci",
            "Nosey Parker": "run: noseyparker scan .",
        }
        for scanner, text in scanners.items():
            with self.subTest(scanner):
                result = _run({**github_steps(text), CI_FILES["GitLab CI"]: ""})
                self.assertEqual(result, Result.passed(f"secrets are scanned for with {scanner}"))

    def test_a_pre_commit_hook_counts(self) -> None:
        hooks = "repos:\n  - repo: https://github.com/gitleaks/gitleaks\n    hooks:\n      - id: gitleaks\n"
        self.assertEqual(_run({".pre-commit-config.yaml": hooks}).status, Status.PASS)

    def test_warns_when_a_configured_scanner_is_not_run(self) -> None:
        result = _run({".gitleaks.toml": "[allowlist]\n"})
        self.assertEqual(
            result, Result.warned("gitleaks is configured, but neither CI nor a pre-commit hook runs it", HINT)
        )
        result = _run({".secrets.baseline": "{}", ".gitguardian.yml": ""})
        self.assertEqual(
            result.message, "detect-secrets, ggshield are configured, but neither CI nor a pre-commit hook runs them"
        )
