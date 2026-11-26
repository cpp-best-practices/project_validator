"""The GitHub Action profile: a repository whose product is an action, its self-test, actionlint and zizmor."""

from __future__ import annotations

import unittest

from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.github_action import GITHUB_ACTION_ECOSYSTEM
from tests.layouts.github_action import ACTION
from tests.support import GITHUB_WORKFLOW, github_action, github_job, make_context, run_in_layout, temp_project

LAYOUT = "GitHub Action"
SELF_TEST = """\
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: shop
        uses: ./
        with:
          prices: "1 2 3"
      - run: test "${{ steps.shop.outputs.total }}" = 6
"""


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_an_action_at_the_root_is_the_repositorys_product(self) -> None:
        for name in ("action.yml", "action.yaml"):
            with self.subTest(name=name), temp_project({name: ACTION}) as root:
                structure = make_context(root).structure
                self.assertEqual(
                    (structure.languages, structure.formats), (frozenset(), frozenset({"GitHub Action", "YAML"}))
                )
                self.assertEqual(structure.recognised_by["GitHub Action"], ("content",))
        # A local action of the repository's own workflows is not its product.
        with temp_project({".github/actions/setup/action.yml": ACTION, "src/main.py": ""}) as root:
            self.assertNotIn("GitHub Action", make_context(root).structure.formats)
        self.assertEqual((GITHUB_ACTION_ECOSYSTEM.kind, GITHUB_ACTION_ECOSYSTEM.toolchain), ("format", None))

    def test_an_action_beside_another_package_is_not_the_product(self) -> None:
        """The action a Python, Lua or other package ships beside itself (psf/black's, lunarmodules/busted's), or a
        workspace's (graphql-inspector's), is a convenience: the repository's product is the package, and no self-test
        is asked of it (upstream #183)."""
        for name, files in {
            "a Python package": {"pyproject.toml": "[project]\nname = 'x'\n", "x.py": ""},
            "a Lua rock": {"busted-scm-1.rockspec": "package = 'busted'\n", "busted.lua": ""},
            "a pnpm workspace": {"pnpm-workspace.yaml": "packages: ['packages/*']\n", "package.json": "{}"},
            "an npm workspace": {"package.json": '{"workspaces": ["packages/*"]}'},
        }.items():
            with self.subTest(case=name), temp_project({"action.yml": ACTION, **files}) as root:
                self.assertNotIn("GitHub Action", make_context(root).structure.formats)
        # A JavaScript action's own package.json, and a Docker action's go.mod, are the action's.
        # Nor are a package of an example or a test below the root, or a package.json that isn't an object of them.
        mine = (
            {"package.json": '{"main": "dist/index.js"}'},
            {"go.mod": "module x\n", "main.go": ""},
            {"examples/demo-1.rockspec": "package = 'demo'\n"},
            {"package.json": "{"},
            {"package.json": '["workspaces"]'},
        )
        for files in mine:
            with self.subTest(files=files), temp_project({"action.yml": ACTION, **files}) as root:
                self.assertIn("GitHub Action", make_context(root).structure.formats)


class GitHubActionTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_a_workflow_using_the_action_is_its_test(self) -> None:
        self.assertEqual(
            self._run(tests_run, {GITHUB_WORKFLOW: SELF_TEST}),
            Result.passed(
                "workflows that use the action itself (uses: ./): 1 file(s), run by the action's own workflow"
            ),
        )
        quoted = SELF_TEST.replace("uses: ./", 'uses: "./"')
        self.assertEqual(self._run(tests_run, {GITHUB_WORKFLOW: quoted}).status, Status.PASS)
        # A local action below the root is not the action itself; a workflow without the step is no self-test.
        local = SELF_TEST.replace("uses: ./", "uses: ./.github/actions/setup")
        self.assertEqual(self._run(tests_run, {GITHUB_WORKFLOW: local}).status, Status.FAIL)
        self.assertEqual(self._run(tests_run, _ci("actionlint")).status, Status.FAIL)

    def test_actionlint_lints_and_zizmor_audits(self) -> None:
        for files in (_ci("actionlint"), github_action("rhysd/actionlint@v1.7.12")):
            with self.subTest(files=files):
                self.assertEqual(self._run(static_analysis, files), Result.passed("actionlint runs"))
        configured = {".github/actionlint.yaml": "self-hosted-runner:\n  labels: []\n", **_ci("actionlint")}
        self.assertEqual(
            self._run(static_analysis, configured), Result.passed("actionlint (.github/actionlint.yaml) runs")
        )
        for files in (
            _ci("pipx run zizmor .github"),
            github_action("zizmorcore/zizmor-action@v0.1", inputs=".github/workflows action.yml"),
            github_action("woodruffw/zizmor-action@v0.1"),
        ):
            with self.subTest(files=files):
                self.assertEqual(
                    self._run(security_scanning, files),
                    Result.passed("CI scans the code for security problems with zizmor"),
                )
        self.assertEqual(self._run(static_analysis, _ci("zizmor .")).status, Status.FAIL)
        self.assertEqual(self._run(security_scanning, _ci("actionlint")).status, Status.WARN)
