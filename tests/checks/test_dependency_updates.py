import unittest

from project_validator.checks.dependency_updates import dependency_updates
from project_validator.core import Result, Status
from tests.support import BARE_PROJECT, PROJECT_LAYOUTS, WELL_CONFIGURED, run_in_every_layout


class DependencyUpdatesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, dependency_updates, files, PROJECT_LAYOUTS)

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(dependency_updates.languages, frozenset())

    def test_warns_without_update_configuration(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no automated dependency updates", result.message)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "automated dependency updates are configured with Dependabot")
        self.assertEqual(result.details, (".github/dependabot.yml",))

    def test_passes_with_any_dependabot_or_renovate_configuration(self) -> None:
        tools = {
            ".github/dependabot.yml": "Dependabot",
            ".github/dependabot.yaml": "Dependabot",
            "renovate.json": "Renovate",
            "renovate.json5": "Renovate",
            ".github/renovate.json": "Renovate",
            ".renovaterc": "Renovate",
            ".renovaterc.json": "Renovate",
        }
        for path, tool in tools.items():
            with self.subTest(path=path):
                result = self._run({path: "{}\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertEqual(result.message, f"automated dependency updates are configured with {tool}")
                self.assertEqual(result.details, (path,))

    def test_configuration_in_the_wrong_directory_does_not_count(self) -> None:
        result = self._run({"dependabot.yml": "version: 2\n", "docs/renovate.json": "{}\n"})
        self.assertEqual(result.status, Status.WARN)
