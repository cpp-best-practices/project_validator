"""Monorepos and mixed-language projects: the units of a project, and questions answered unit by unit."""

import json
import unittest

from project_validator.checks.coverage import coverage
from project_validator.core import Result, Status
from project_validator.facts.structure import Unit
from tests.support import GITHUB_WORKFLOW, make_context, temp_project


def _workflow(*steps: tuple[str, str | None]) -> dict[str, str]:
    """A GitHub workflow running each (command, working directory)."""
    runs = [{"run": run, **({"working-directory": directory} if directory else {})} for run, directory in steps]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": runs}}})}


def _package(name: str) -> dict[str, str]:
    return {
        f"packages/{name}/package.json": json.dumps({"name": name, "main": "index.js"}),
        f"packages/{name}/index.js": "",
    }


WORKSPACES = {
    "package.json": json.dumps({"private": True, "workspaces": ["packages/*"]}),
    **_package("a"),
    **_package("b"),
}
MIXED = {
    "CMakeLists.txt": "project(app CXX)\n",
    "src/main.cpp": "",
    "python/pyproject.toml": "[project]\nname = 'bindings'\n",
    "python/bindings/__init__.py": "",
}


def _units(files: dict[str, str]) -> list[tuple[str, tuple[str, ...], list[str]]]:
    with temp_project(files) as root:
        return [
            (unit.directory, unit.build_systems, sorted(unit.languages)) for unit in make_context(root).facts.of(Unit)
        ]


def _coverage(files: dict[str, str]) -> Result:
    with temp_project(files) as root:
        return coverage.run(make_context(root))


class UnitTests(unittest.TestCase):
    def test_a_project_built_from_its_root_is_one_unit(self) -> None:
        nested = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "src/main.cpp": "", "test/CMakeLists.txt": ""}
        self.assertEqual(_units(nested), [(".", ("CMake",), ["C", "C++"])])

    def test_workspace_members_are_units_of_their_own(self) -> None:
        self.assertEqual(
            _units(WORKSPACES),
            [(".", ("npm",), []), ("packages/a", ("npm",), ["JavaScript"]), ("packages/b", ("npm",), ["JavaScript"])],
        )
        cargo = {
            "Cargo.toml": '[workspace]\nmembers = ["crates/*"]\n',
            **{f"crates/{name}/Cargo.toml": "[package]\n" for name in ("x", "y")},
            **{f"crates/{name}/src/lib.rs": "" for name in ("x", "y")},
        }
        self.assertEqual(
            _units(cargo),
            [(".", ("Cargo",), []), ("crates/x", ("Cargo",), ["Rust"]), ("crates/y", ("Cargo",), ["Rust"])],
        )
        broken = {"package.json": "{", **_package("a")}
        self.assertEqual([unit for unit, _, _ in _units(broken)], ["."])
        go = {"go.work": "go 1.23\n\nuse (\n\t./api\n\t./cli\n)\n", "api/go.mod": "", "api/a.go": "", "cli/go.mod": ""}
        self.assertEqual([unit for unit, _, _ in _units(go)], [".", "api", "cli"])

    def test_a_mixed_language_project_has_a_unit_per_build_root(self) -> None:
        self.assertEqual(
            _units(MIXED), [(".", ("CMake",), ["C", "C++"]), ("python", ("Python packaging",), ["Python"])]
        )


class MonorepoCoverageTests(unittest.TestCase):
    def test_each_unit_needs_coverage_and_findings_name_the_unit(self) -> None:
        result = _coverage({**WORKSPACES, **_workflow(("npx c8 node --test", "packages/a"))})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "packages/a: branch coverage is reported with c8; "
            "packages/b: no branch coverage reporting found in what CI runs",
        )

    def test_a_run_from_the_root_covers_every_unit(self) -> None:
        result = _coverage({**WORKSPACES, **_workflow(("npx c8 node --test", None))})
        self.assertEqual(result, Result.passed("branch coverage is reported with c8"))

    def test_each_language_of_a_mixed_project_is_judged_where_it_is(self) -> None:
        both = _workflow(("gcovr --xml cov.xml", None), ("coverage run --branch -m pytest", "python"))
        result = _coverage({**MIXED, **both})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("Python: branch coverage is reported with coverage.py", result.message)
        only_cpp = _coverage({**MIXED, **_workflow(("gcovr --xml cov.xml", None))})
        self.assertIn("Python: no branch coverage reporting found in what CI runs", only_cpp.message)
