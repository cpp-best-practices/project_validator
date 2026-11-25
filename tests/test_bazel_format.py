"""Bazel's own files as a format: recognised by `*.bazel`, `*.bzl` and `WORKSPACE`, formatted and linted by
buildifier, beside the language they build."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from tests.support import github_job, make_context, run_in_layout, temp_project

MODULES = "Bazel modules"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


_HOOKS = "repos:\n  - repo: https://github.com/keith/pre-commit-buildifier\n    rev: 8.0.0\n    hooks:\n"


class RecognitionTests(unittest.TestCase):
    def test_bazel_files_are_a_format_beside_the_language_they_build(self) -> None:
        files = {
            "MODULE.bazel": 'module(name = "app")\n',
            "BUILD.bazel": 'cc_library(name = "app", srcs = ["src/main.cc"])\n',
            "tools/defs.bzl": "def app_test(name):\n    pass\n",
            "WORKSPACE.bzlmod": "",
            "ci/linux.bazelrc": "build --copt=-Werror\n",
            "src/main.cc": "",
        }
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, "Bazel" in structure.formats), (frozenset({"C++"}), True))
        self.assertEqual(structure.unrecognised_suffixes, ())

    def test_a_workspace_file_alone_makes_bazel_files(self) -> None:
        with temp_project({"WORKSPACE": 'workspace(name = "app")\n', "src/main.cc": ""}) as root:
            self.assertIn("Bazel", make_context(root).structure.formats)

    def test_a_build_file_alone_is_not_bazel(self) -> None:
        # Pants names its build files BUILD too.
        with temp_project({"BUILD": 'python_sources(name = "lib")\n', "src/app.py": ""}) as root:
            self.assertNotIn("Bazel", make_context(root).structure.formats)


class BuildifierTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, MODULES, selected, files)

    def test_buildifier_checks_the_formatting_in_check_or_diff_mode(self) -> None:
        for line in (
            "buildifier -mode=check -r .",
            "buildifier --mode=diff -r .",
            "buildifier -d MODULE.bazel",
            "buildifier --mode=fix --mode=check -r .",  # the last wins
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run(code_formatting, _ci(line)), Result.passed("CI enforces the buildifier style")
                )
        styled = {".buildifier.json": '{"type": "auto"}\n', **_ci("buildifier -mode=check -r .")}
        self.assertEqual(
            self._run(code_formatting, styled).message, ".buildifier.json is defined and CI runs buildifier"
        )

    def test_buildifier_rewriting_the_files_enforces_nothing(self) -> None:
        for line in ("buildifier -r .", "buildifier -mode=fix -r .", "buildifier -mode=check -mode=fix -r ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)
                # Unless the job fails on what it changed.
                self.assertEqual(self._run(code_formatting, _ci(line, "git diff --exit-code")).status, Status.PASS)

    def test_buildifier_printing_what_it_would_change_formats_nothing(self) -> None:
        result = self._run(code_formatting, _ci("buildifier -mode=print_if_changed -r .", "git diff --exit-code"))
        self.assertEqual(result.status, Status.FAIL)

    def test_buildifier_lints_with_lint_warn_or_fix(self) -> None:
        for line in ("buildifier -lint=warn -r .", "buildifier --lint fix -mode=check -r ."):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)), Result.passed("buildifier runs"))
        for line in (
            "buildifier -mode=check -r .",
            "buildifier -lint=off -r .",
            "buildifier -lint=warn -lint=off .",
            "starlark-lint -lint=warn .",  # another program
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)).status, Status.FAIL)

    def test_the_pre_commit_hooks_format_and_lint_where_ci_runs_them(self) -> None:
        ci = _ci("pre-commit run --all-files")
        formatting = {".pre-commit-config.yaml": _HOOKS + "      - id: buildifier\n", **ci}
        self.assertEqual(self._run(code_formatting, formatting).status, Status.PASS)
        # The buildifier hook fixes what the linter can, and fails on the rest.
        self.assertEqual(self._run(static_analysis, formatting).status, Status.PASS)
        linting = {".pre-commit-config.yaml": _HOOKS + "      - id: buildifier-lint\n", **ci}
        self.assertEqual(self._run(static_analysis, linting).status, Status.PASS)

    def test_a_cxx_projects_bazel_files_are_judged_beside_its_cxx(self) -> None:
        files = {
            "MODULE.bazel": 'module(name = "app")\n',
            "BUILD.bazel": 'cc_binary(name = "app", srcs = ["main.cc"])\n',
            "main.cc": "int main() {}\n",
            ".clang-format": "BasedOnStyle: LLVM\n",
        }
        with temp_project({**files, **_ci("clang-format --dry-run -Werror main.cc")}) as root:
            result = code_formatting.run(make_context(root))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("Bazel: CI never runs buildifier", result.message)
        steps = ("clang-format --dry-run -Werror main.cc", "buildifier -mode=check -r .")
        with temp_project({**files, **_ci(*steps)}) as root:
            self.assertEqual(code_formatting.run(make_context(root)).status, Status.PASS)
