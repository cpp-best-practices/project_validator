from __future__ import annotations

import unittest

from project_validator.checks.ci_present import ci_present
from project_validator.core import Result, Status
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED,
    make_context,
    run_in_every_layout,
    temp_project,
)


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
        # Without a ci: section the hooks are run locally: the local checks, judged at an entry level (upstream #384).
        for text in ("repos: []\n", "ci: ["):
            with self.subTest(text=text):
                local = self._run({".pre-commit-config.yaml": text})
                self.assertEqual(local.status, Status.WARN)
                self.assertIn("pre-commit run --all-files", local.message)

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

    def test_fails_when_its_only_ci_is_defunct(self) -> None:
        """A CI that no longer runs is no CI: a .travis.yml whose README shows only travis-ci.org's badge."""
        files = {
            ".travis.yml": "language: cpp\n",
            "README.md": "[![b](https://travis-ci.org/o/r.svg)](https://travis-ci.org/o/r)\n",
        }
        with temp_project(files) as root:
            result = ci_present.run(make_context(root))
        self.assertEqual(
            result, Result.failed("only defunct CI configuration found: Travis CI (.travis.yml); see ci-current")
        )
