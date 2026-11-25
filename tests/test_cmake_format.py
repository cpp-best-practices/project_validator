"""CMake code as a format: recognised by `CMakeLists.txt` and `*.cmake`, formatted by gersemi or cmake-format and
linted by cmake-lint or cmakelint, beside the language it builds."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from tests.support import github_job, make_context, run_in_layout, temp_project

MODULES = "CMake modules"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _hook(repo: str, hook: str) -> dict[str, str]:
    return {".pre-commit-config.yaml": f"repos:\n  - repo: {repo}\n    rev: v1\n    hooks:\n      - id: {hook}\n"}


class RecognitionTests(unittest.TestCase):
    def test_cmake_code_is_a_format_beside_the_language_it_builds(self) -> None:
        files = {"CMakeLists.txt": "project(app CXX)\n", "cmake/Warnings.cmake": "", "src/main.cpp": ""}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, "CMake" in structure.formats), (frozenset({"C++"}), True))
        self.assertEqual(structure.unrecognised_suffixes, ())


class CMakeFormattingTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, MODULES, selected, files)

    def test_gersemi_and_cmake_format_check_the_formatting(self) -> None:
        for line, tool in (
            ("gersemi --check .", "gersemi"),
            ("gersemi --diff cmake", "gersemi"),
            ("cmake-format --check CMakeLists.txt", "cmake-format"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)), Result.passed(f"CI enforces the {tool} style"))
        styled = {".gersemirc": "line_length: 100\n", **_ci("gersemi --check .")}
        self.assertEqual(self._run(code_formatting, styled).message, ".gersemirc is defined and CI runs gersemi")
        # Rewriting the files without failing on what changed enforces nothing.
        for line in ("gersemi -i .", "cmake-format -i CMakeLists.txt"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)

    def test_the_pre_commit_hooks_format_where_ci_runs_them(self) -> None:
        for hook in (
            _hook("https://github.com/BlankSpruce/gersemi", "gersemi"),
            _hook("https://github.com/cheshirekow/cmake-format-precommit", "cmake-format"),
        ):
            with self.subTest(hook=hook):
                result = self._run(code_formatting, {**hook, **_ci("pre-commit run --all-files")})
                self.assertEqual(result.status, Status.PASS, result)

    def test_cmake_lint_and_cmakelint_lint_it(self) -> None:
        for line, tool in (("cmake-lint CMakeLists.txt", "cmake-lint"), ("cmakelint CMakeLists.txt", "cmakelint")):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)), Result.passed(f"{tool} runs"))
        self.assertEqual(self._run(static_analysis, _ci("cmake -B build")).status, Status.FAIL)

    def test_cmake_warnings_are_errors_with_werror_dev(self) -> None:
        """`cmake -Werror=dev` (or a configure preset's `errors: {dev: true}`) makes CMake's warnings for the project
        errors; without it, warnings-as-errors fails."""
        passed = Result.passed("warnings are treated as errors with cmake -Werror=dev")
        self.assertEqual(self._run(warnings_as_errors, _ci("cmake -S . -B build -Werror=dev")), passed)
        presets = {
            "CMakePresets.json": '{"version": 6, "configurePresets": [{"name": "ci", "errors": {"dev": true}}]}\n'
        }
        self.assertEqual(self._run(warnings_as_errors, {**presets, **_ci("cmake --preset ci")}).status, Status.PASS)
        for line in ("cmake -S . -B build", "cmake -S . -B build -Wdev"):
            with self.subTest(line=line):
                self.assertEqual(self._run(warnings_as_errors, _ci(line)).status, Status.FAIL)

    def test_a_cxx_projects_cmake_code_is_judged_beside_its_cxx(self) -> None:
        """fmt and cmake_template format their CMake code too; a C++ project's CMake code is asked to be formatted
        and linted as its C++ is."""
        files = {
            "CMakeLists.txt": "project(app CXX)\nadd_executable(app src/main.cpp)\n",
            "src/main.cpp": "int main() {}\n",
            ".clang-format": "BasedOnStyle: LLVM\n",
        }
        with temp_project({**files, **_ci("clang-format --dry-run -Werror src/main.cpp")}) as root:
            result = code_formatting.run(make_context(root))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("CMake: CI never runs gersemi or cmake-format", result.message)
        with temp_project({**files, **_ci("clang-format --dry-run -Werror src/main.cpp", "gersemi --check .")}) as root:
            self.assertEqual(code_formatting.run(make_context(root)).status, Status.PASS)
