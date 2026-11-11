from __future__ import annotations

import unittest

from project_validator.checks.copy_paste_detection import copy_paste_detection
from project_validator.core import Result, Status
from tests.support import FIXTURES, github_steps, make_context, temp_project


class CopyPasteDetectionTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(copy_paste_detection.languages, frozenset())

    def _run(self, files: dict[str, str]) -> Result:
        with temp_project(files) as root:
            return copy_paste_detection.run(make_context(root))

    def test_warns_without_ci(self) -> None:
        result = copy_paste_detection.run(make_context(FIXTURES / "bare_c_cpp"))
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_copy_paste_detection(self) -> None:
        result = self._run(github_steps("run: ctest --test-dir build"))
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no copy-paste detection", result.message)

    def test_passes_with_pmd_cpd(self) -> None:
        result = copy_paste_detection.run(make_context(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs copy-paste detection with PMD CPD")

    def test_detects_known_tools(self) -> None:
        cases = (
            ("run: pmd cpd --language cpp --minimum-tokens 100 --dir src", "PMD CPD"),
            ("run: ./pmd-bin/bin/run.sh cpd --files src --language cpp", "PMD CPD"),
            ("run: npx jscpd --format cpp src", "jscpd"),
            ("run: duplo -ml 20 files.txt duplicates.txt", "Duplo"),
            ("run: java -jar simian-4.0.0.jar '**/*.cpp'", "Simian"),
            ("run: ccfx d cpp -d src", "CCFinderX"),
            ("uses: SonarSource/sonarqube-scan-action@v5", "SonarQube"),
            ("uses: SonarSource/sonarcloud-github-action@v3", "SonarQube"),
            ("run: sonar-scanner -Dsonar.projectKey=demo", "SonarQube"),
        )
        for step, tool in cases:
            with self.subTest(tool=tool, step=step):
                result = self._run(github_steps(step))
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, f"CI runs copy-paste detection with {tool}")

    def test_lists_every_tool_found(self) -> None:
        result = self._run({".gitlab-ci.yml": "cpd:\n  script:\n    - pmd cpd --dir src\n    - jscpd src\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs copy-paste detection with PMD CPD, jscpd")

    def test_similar_words_do_not_count(self) -> None:
        result = self._run(github_steps("run: ./duplicate.sh cpdfile duplogs"))
        self.assertEqual(result.status, Status.WARN)

    def test_tool_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# pmd cpd --language cpp --dir src\n"})
        self.assertEqual(result.status, Status.WARN)
