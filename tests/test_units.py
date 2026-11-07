"""Monorepos and mixed-language projects: the units of a project, and questions answered unit by unit."""

import json
import unittest

from project_validator.checks.coverage import coverage
from project_validator.core import Result, Status
from project_validator.facts import CiJob, Command, Unknown
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

    def test_yarn_workspaces_under_packages_and_vendored_projects(self) -> None:
        yarn = {"package.json": json.dumps({"workspaces": {"packages": ["packages/*"]}}), **_package("a")}
        self.assertEqual([unit for unit, _, _ in _units(yarn)], [".", "packages/a"])
        vendored = {"CMakeLists.txt": "", "main.c": "", "deps/lib/package.json": "{}", "deps/lib/x.js": ""}
        self.assertEqual([unit for unit, _, _ in _units(vendored)], ["."])

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

    def test_a_run_outside_the_project_covers_none_of_it(self) -> None:
        result = _coverage({**MIXED, **_workflow(("cd /tmp/other && gcovr --xml x", None))})
        self.assertIn("C/C++: no branch coverage reporting found in what CI runs", result.message)

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


def _scripts(files: dict[str, str]) -> list[tuple[tuple[str, ...], str | None]]:
    """The scripts of the workspace packages (each runs `vitest <package>`) that CI runs, and where they run."""
    with temp_project(files) as root:
        commands = make_context(root).facts.of(Command)
    return [(command.argv, command.directory) for command in commands if command.argv[0] == "vitest"]


MEMBERS = {
    **{f"packages/{name}/package.json": json.dumps({"scripts": {"test": f"vitest {name}"}}) for name in ("a", "b")},
    "packages/c/package.json": "{}",
}
CALLED_WORKFLOW = """on: workflow_call
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: gcovr --xml x
"""


class WorkspaceScriptTests(unittest.TestCase):
    def test_a_script_run_across_the_workspace_runs_each_packages_script(self) -> None:
        npm = {"package.json": json.dumps({"workspaces": ["packages/*"]}), **MEMBERS}
        pnpm = {
            "package.json": "{}",
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n  - '!packages/c'\n",
            **MEMBERS,
        }
        expected = [(("vitest", "a"), "packages/a"), (("vitest", "b"), "packages/b")]
        for files, line in (
            (npm, "npm run test --workspaces"),
            (npm, "npm test -ws"),
            (pnpm, "pnpm -r test"),
            (pnpm, "pnpm --filter ./packages/* run test"),
            (pnpm, "npx turbo run test"),
            (pnpm, "turbo test --filter=a"),
            (npm, "lerna run test"),
            (npm, "nx run-many -t test,lint"),
        ):
            with self.subTest(line=line):
                self.assertEqual(_scripts({**files, **_workflow((line, None))}), expected)
        self.assertEqual(_scripts({**npm, **_workflow(("nx graph", None), ("lerna version", None))}), [])
        broken = {"package.json": "{}", "pnpm-workspace.yaml": "packages: [", **MEMBERS}
        self.assertEqual(_scripts({**broken, **_workflow(("pnpm -r test", None))}), [])


class ReusableWorkflowTests(unittest.TestCase):
    def _facts(self, uses: str) -> tuple[list[str], list[str]]:
        caller = {
            GITHUB_WORKFLOW: json.dumps({"jobs": {"ci": {"uses": uses}}}),
            ".github/workflows/_build.yml": CALLED_WORKFLOW,
        }
        with temp_project(caller) as root:
            facts = make_context(root).facts
        return [job.id for job in facts.of(CiJob)], [unknown.subject for unknown in facts.of(Unknown)]

    def test_a_reusable_workflow_of_the_same_repository_is_read(self) -> None:
        for uses in ("./.github/workflows/_build.yml", "$/.github/workflows/_build.yml"):
            with self.subTest(uses=uses):
                jobs, unknowns = self._facts(uses)
                self.assertEqual(jobs, [f"{GITHUB_WORKFLOW}:ci → .github/workflows/_build.yml:build"])
                self.assertEqual(unknowns, [])

    def test_one_in_another_repository_or_missing_is_unknown(self) -> None:
        for uses in ("org/repo/.github/workflows/build.yml@v1", "./.github/workflows/missing.yml"):
            with self.subTest(uses=uses):
                self.assertEqual(self._facts(uses), ([], ["job ci"]))
