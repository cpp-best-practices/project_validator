import importlib
import pkgutil
import unittest
from pathlib import Path

from project_validator import checks
from project_validator.core import Check
from project_validator.plugins import PluginError, discover
from tests.support import temp_project

CHECK_MODULES = tuple(sorted(info.name for info in pkgutil.iter_modules(checks.__path__)))
CHECK_TESTS = Path(__file__).parent / "checks"
KEBAB_CASE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

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
        self.assertEqual(len(plugins.checks), len(CHECK_MODULES))
        self.assertTrue({"GitHub Actions", "GitLab CI", "Travis CI"} <= {p.name for p in plugins.providers})

    def test_every_built_in_check_module_defines_exactly_one_check(self) -> None:
        for name in CHECK_MODULES:
            with self.subTest(module=name):
                module = importlib.import_module(f"{checks.__name__}.{name}")
                self.assertEqual(len([value for value in vars(module).values() if isinstance(value, Check)]), 1)

    def test_built_in_check_names_are_unique_and_kebab_case(self) -> None:
        names = [found.name for found in discover().checks]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            with self.subTest(check=name):
                self.assertRegex(name, KEBAB_CASE)

    def test_every_built_in_check_module_has_its_own_test_file(self) -> None:
        for name in CHECK_MODULES:
            with self.subTest(module=name):
                self.assertTrue((CHECK_TESTS / f"test_{name}.py").is_file())

    def test_loads_extra_plugin_directories(self) -> None:
        with temp_project({"readme.py": PLUGIN}) as directory:
            plugins = discover([directory])
        self.assertIn("readme", [c.name for c in plugins.checks])
        self.assertIn("Example CI", [p.name for p in plugins.providers])

    def test_rejects_duplicate_check_names(self) -> None:
        with (
            temp_project({"a.py": PLUGIN, "b.py": PLUGIN}) as directory,
            self.assertRaisesRegex(PluginError, "duplicate check name"),
        ):
            discover([directory])

    def test_reports_broken_plugins(self) -> None:
        with (
            temp_project({"broken.py": "raise RuntimeError('boom')"}) as directory,
            self.assertRaisesRegex(PluginError, "boom"),
        ):
            discover([directory])

    def test_reports_missing_plugin_directories(self) -> None:
        with temp_project({}) as directory, self.assertRaisesRegex(PluginError, "does not exist"):
            discover([directory / "missing"])
