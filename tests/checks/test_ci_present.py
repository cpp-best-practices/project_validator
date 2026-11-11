from __future__ import annotations

import unittest

from project_validator.checks.ci_present import ci_present
from project_validator.core import Result, Status
from tests.support import BARE_PROJECT, CI_FILES, PROJECT_LAYOUTS, WELL_CONFIGURED, run_in_every_layout


class CiPresentTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, ci_present, files, PROJECT_LAYOUTS)

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(ci_present.languages, frozenset())

    def test_passes_with_ci(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("GitHub Actions", result.message)

    def test_pre_commit_ci_is_a_pre_commit_configuration_with_a_ci_section(self) -> None:
        configured = self._run({".pre-commit-config.yaml": "ci:\n  autofix_prs: false\nrepos: []\n"})
        self.assertEqual(configured.message, "CI configuration found for pre-commit.ci")
        self.assertEqual(self._run({".pre-commit-config.yaml": "repos: []\n"}).status, Status.FAIL)
        self.assertEqual(self._run({".pre-commit-config.yaml": "ci: ["}).status, Status.FAIL)

    def test_passes_with_every_ci_provider(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "jobs: {}\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, f"CI configuration found for {provider}")
                self.assertEqual(result.details, (path,))

    def test_fails_without_ci_and_lists_what_was_searched(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("GitLab CI", result.message)
