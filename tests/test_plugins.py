import unittest

from project_validator.plugins import PluginError, discover
from tests.support import temp_project

PLUGIN = """
from project_validator.ci import CiProvider
from project_validator.core import Result, check

EXAMPLE_CI = CiProvider(name="Example CI", files=("example-ci.yml",))


@check(name="readme", description="Has a README")
def readme(context):
    return Result.passed("ok") if context.project.exists("README.md") else Result.failed("missing")
"""


class DiscoverTests(unittest.TestCase):
    def test_discovers_built_in_checks_and_providers(self) -> None:
        plugins = discover()
        self.assertEqual(
            sorted(c.name for c in plugins.checks),
            [
                "ci-present",
                "coverage",
                "ctest-runs",
                "cxx-extensions",
                "platform-matrix",
                "security-scanning",
                "warnings-as-errors",
            ],
        )
        self.assertTrue({"GitHub Actions", "GitLab CI", "Travis CI"} <= {p.name for p in plugins.providers})

    def test_loads_extra_plugin_directories(self) -> None:
        with temp_project({"readme.py": PLUGIN}) as directory:
            plugins = discover([directory])
        self.assertIn("readme", [c.name for c in plugins.checks])
        self.assertIn("Example CI", [p.name for p in plugins.providers])

    def test_rejects_duplicate_check_names(self) -> None:
        with temp_project({"a.py": PLUGIN, "b.py": PLUGIN}) as directory:
            with self.assertRaisesRegex(PluginError, "duplicate check name"):
                discover([directory])

    def test_reports_broken_plugins(self) -> None:
        with temp_project({"broken.py": "raise RuntimeError('boom')"}) as directory:
            with self.assertRaisesRegex(PluginError, "boom"):
                discover([directory])

    def test_reports_missing_plugin_directories(self) -> None:
        with temp_project({}) as directory:
            with self.assertRaisesRegex(PluginError, "does not exist"):
                discover([directory / "missing"])
