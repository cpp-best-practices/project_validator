import importlib
import pkgutil
import unittest
from pathlib import Path

from project_validator import checks
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import applies_to, isolated_registry, registered
from project_validator.plugins import PluginError, Plugins, discover
from project_validator.runner import run_check
from tests.support import make_context, temp_project

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


# A whole ecosystem from a plugin: detected by its build file and source suffix, judged by the practices it has rules
# for, and seen by --list.
ECOSYSTEM_PLUGIN = """
import re

from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.rules import Formatter
from project_validator.text import pattern


def _no_config(context):
    return None


GO = Ecosystem(
    label="Go",
    languages=frozenset({"Go"}),
    build_systems=(BuildSystem(name="Go modules", files=("go.mod",), languages=frozenset({"Go"})),),
    source_suffixes={".go": "Go"},
    toolchain=ToolchainPatterns(
        language="Go", versions=(re.compile(r"\\bgo-version\\W+([\\d.x]+)"),), usage=re.compile(r"\\bgo\\s+test\\b")
    ),
    rules=(
        versions_axis("Go version", "Go"),
        Formatter(
            name="gofmt",
            config_file=_no_config,
            runs=(pattern("gofmt", r"\\bgofmt\\b"),),
            hint="run gofmt -l in CI",
            default_style=True,
        ),
    ),
)
"""

GO_PROJECT = {
    "go.mod": "module example.com/demo\n",
    "main.go": "package main\n",
    ".github/workflows/ci.yml": (
        "jobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/setup-go@v5\n"
        "        with:\n          go-version: '1.23'\n      - run: test -z \"$(gofmt -l .)\"\n"
    ),
}


class EcosystemPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = isolated_registry()
        registry.__enter__()
        self.addCleanup(registry.__exit__, None, None, None)

    def _discover_go(self) -> Plugins:
        with temp_project({"go.py": ECOSYSTEM_PLUGIN}) as directory:
            return discover([directory])

    def test_a_plugin_ecosystem_is_registered_and_practices_apply_to_it(self) -> None:
        plugins = self._discover_go()
        self.assertEqual([ecosystem.label for ecosystem in registered()], ["C/C++", "Python", "Rust", "Go"])
        formatting = next(found for found in plugins.checks if found.name == "code-formatting")
        self.assertIn("Go", formatting.languages)
        self.assertIn("Go", applies_to(formatting))

    def test_a_plugin_ecosystem_is_detected_and_judged(self) -> None:
        plugins = self._discover_go()
        checks = {found.name: found for found in plugins.checks}
        with temp_project(GO_PROJECT) as root:
            context = make_context(root)
            self.assertEqual(context.structure.languages, frozenset({"Go"}))
            self.assertEqual(context.structure.build_systems, frozenset({"Go modules"}))
            self.assertEqual(
                run_check(checks["code-formatting"], context), Result.passed("CI enforces the gofmt style")
            )
            self.assertEqual(run_check(checks["coverage"], context).status, Status.SKIP)
            self.assertIn("1.23", run_check(checks["platform-matrix"], context).message)

    def test_loading_a_plugin_again_replaces_its_ecosystem(self) -> None:
        self._discover_go()
        self._discover_go()
        self.assertEqual([ecosystem.label for ecosystem in registered()], ["C/C++", "Python", "Rust", "Go"])

    def test_rejects_an_ecosystem_with_a_built_in_label(self) -> None:
        clash = ECOSYSTEM_PLUGIN.replace('label="Go"', 'label="Python"')
        with (
            temp_project({"clash.py": clash}) as directory,
            self.assertRaisesRegex(PluginError, "Python is a built-in ecosystem"),
        ):
            discover([directory])

    def test_rejects_two_plugin_ecosystems_with_the_same_label(self) -> None:
        with (
            temp_project({"a.py": ECOSYSTEM_PLUGIN, "b.py": ECOSYSTEM_PLUGIN}) as directory,
            self.assertRaisesRegex(PluginError, "duplicate ecosystem label"),
        ):
            discover([directory])

    def test_the_registry_is_restored_after_isolation(self) -> None:
        with isolated_registry():
            self._discover_go()
        self.assertEqual(len(registered()), 3)
