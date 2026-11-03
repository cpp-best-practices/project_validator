import unittest

from project_validator.checks.security_scanning import security_scanning
from project_validator.core import Result, Status
from tests.support import BARE_PROJECT, CI_FILES, PROJECT_LAYOUTS, WELL_CONFIGURED, run_in_every_layout


class SecurityScanningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, security_scanning, files, PROJECT_LAYOUTS)

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(security_scanning.languages, frozenset())

    def test_warns_without_ci(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_code_scanning(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "steps:\n  - run: ctest --test-dir build\n"})
                self.assertEqual(result.status, Status.WARN)
                self.assertIn("no code security scanning", result.message)

    def test_passes_with_codeql(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with CodeQL")

    def test_passes_with_the_gitlab_sast_template(self) -> None:
        result = self._run({".gitlab-ci.yml": "include:\n  - template: Security/SAST.gitlab-ci.yml\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with GitLab SAST")

    def test_codeql_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# uses: github/codeql-action/analyze@v3\n"})
        self.assertEqual(result.status, Status.WARN)
