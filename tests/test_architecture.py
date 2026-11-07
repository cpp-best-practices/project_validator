"""The structure that keeps ecosystems and practices apart: profiles hold ecosystem knowledge, checks stay generic."""

import ast
import importlib
import pkgutil
import sys
import unittest
from pathlib import Path

import project_validator
from project_validator import ecosystems
from project_validator.core import Context, Result
from project_validator.ecosystems import BUILT_IN, PROFILES, Ecosystem, languages_of
from project_validator.rules import FunctionLimits
from tests import layouts as tests_layouts

PACKAGE = Path(project_validator.__file__).parent
CHECKS = PACKAGE / "checks"
PROFILE_MODULES = frozenset(
    f"project_validator.ecosystems.{module.name}"
    for module in pkgutil.iter_modules(ecosystems.__path__)
    if module.name != "model"
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found |= {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}
        elif isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
    return found


def _is_profile(module: str) -> bool:
    return any(module == profile or module.startswith(f"{profile}.") for profile in PROFILE_MODULES)


def _all_modules() -> list[str]:
    """Every module of the package, except `__main__`, which runs the validator when imported."""
    names = (".".join(path.relative_to(PACKAGE).with_suffix("").parts) for path in PACKAGE.rglob("*.py"))
    return sorted(f"project_validator.{name}".removesuffix(".__init__") for name in names if name != "__main__")


def _import_fresh(module: str) -> None:
    """Import `module` as if nothing of the package were imported yet, then put the original modules back."""
    saved = dict(sys.modules)
    try:
        for name in [name for name in sys.modules if name.split(".")[0] == "project_validator"]:
            del sys.modules[name]
        importlib.import_module(module)
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def _limits(_name: str) -> FunctionLimits:
    def never(_: Context) -> Result:
        return Result.failed("never limited")

    return FunctionLimits(without_lizard=never)


class ArchitectureTests(unittest.TestCase):
    def test_checks_never_import_an_ecosystem_profile(self) -> None:
        for path in sorted(CHECKS.glob("*.py")):
            with self.subTest(check=path.stem):
                profiles = sorted(module for module in _imported_modules(path) if _is_profile(module))
                self.assertEqual(profiles, [])

    def test_checks_never_name_languages(self) -> None:
        """Even a practice only one ecosystem has, such as cxx-extensions, gets its languages from the registry (or
        from the components that measure them)."""
        languages = languages_of(BUILT_IN)
        for path in sorted(CHECKS.glob("*.py")):
            with self.subTest(check=path.stem):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("project_validator.ecosystems.C_FAMILY", _imported_modules(path))
                self.assertNotRegex(text, r"languages=(?:frozenset\(\s*)?[{\[(]")
                self.assertEqual([language for language in languages if f'"{language}"' in text], [])

    def test_rules_never_import_the_ecosystems(self) -> None:
        imported = _imported_modules(PACKAGE / "rules.py")
        self.assertEqual(sorted(module for module in imported if module.startswith("project_validator.ecosystems")), [])

    def test_every_module_imports_on_its_own(self) -> None:
        """An import cycle shows up only for the module that is imported first, so each one is tried first."""
        for module in _all_modules():
            with self.subTest(module=module):
                _import_fresh(module)


class ProfileTests(unittest.TestCase):
    """A profile is found by its module, so adding one edits no shared list."""

    def test_each_profile_module_defines_one_ecosystem(self) -> None:
        for name in sorted(PROFILES):
            module = importlib.import_module(f"project_validator.ecosystems.{name}")
            with self.subTest(profile=name):
                found = {id(value) for value in vars(module).values() if isinstance(value, Ecosystem)}
                self.assertEqual(found, {id(PROFILES[name])})

    def test_every_profile_is_built_in(self) -> None:
        self.assertEqual(set(BUILT_IN), set(PROFILES.values()))
        self.assertEqual({f"project_validator.ecosystems.{name}" for name in PROFILES}, PROFILE_MODULES)

    def test_every_profile_has_test_layouts(self) -> None:
        layouts = {module.name for module in pkgutil.iter_modules(tests_layouts.__path__)} - {"model"}
        self.assertEqual(layouts, set(PROFILES))


class EcosystemRuleTests(unittest.TestCase):
    def test_an_ecosystem_has_at_most_one_rule_of_each_type(self) -> None:
        for ecosystem in BUILT_IN:
            with self.subTest(ecosystem=ecosystem.label):
                kinds = [type(rule) for rule in ecosystem.rules]
                self.assertEqual(len(kinds), len(set(kinds)))
        with self.assertRaisesRegex(ValueError, "several rules of type FunctionLimits"):
            Ecosystem(label="Twice", languages=frozenset({"X"}), rules=(_limits("a"), _limits("b")))

    def test_a_missing_rule_is_none(self) -> None:
        ecosystem = Ecosystem(label="Bare", languages=frozenset({"X"}))
        self.assertIsNone(ecosystem.rule(FunctionLimits))
        self.assertEqual(repr(ecosystem), "Ecosystem(Bare)")
