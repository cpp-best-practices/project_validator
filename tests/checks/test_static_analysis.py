from __future__ import annotations

import unittest

from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.facts import Facts
from project_validator.facts.analysis import ANALYSIS, CHECKS, TYPE_CHECK, Strictness
from project_validator.policy.analysis import judge_analysis, judge_type_checking
from project_validator.questions.tooling import tool_answer
from tests.support import (
    BARE_PROJECT,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_GO,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    github_job,
    run_as,
    run_in_every_layout,
)

C_HINT = (
    "consider running clang-tidy (CMAKE_CXX_CLANG_TIDY, checks chosen in a .clang-tidy) and cppcheck "
    "(CMAKE_CXX_CPPCHECK) in CI"
)
PYTHON_HINT = "consider running ruff check, pylint or flake8 in CI"
GO_HINT = "consider running golangci-lint (with linters enabled beyond its defaults in a .golangci.yml) in CI"
RUST_HINT = "consider running cargo clippy in CI"
DEFAULTS = "{} has no configuration of its checks, so it runs only its defaults"
CLANG_TIDY_CONFIG = {".clang-tidy": "Checks: 'bugprone-*'\n"}
GOLANGCI_CI = github_job("ubuntu-latest", "golangci-lint run ./...")
CONFIGURES = github_job("ubuntu-latest", "cmake -S . -B build")


class StaticAnalysisTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertLessEqual(C_FAMILY | {"Python", "Rust", "Go"}, static_analysis.languages)

    def test_well_configured_projects_pass(self) -> None:
        cases = (
            (WELL_CONFIGURED, (C_AND_CXX,), "clang-tidy (.clang-tidy) and cppcheck run"),
            (WELL_CONFIGURED_PYTHON, (PYTHON,), "ruff check runs"),
            (WELL_CONFIGURED_RUST, (RUST,), "clippy (Cargo.toml) runs"),
            (WELL_CONFIGURED_GO, (GO,), "golangci-lint (.golangci.yml) runs"),
        )
        for files, ecosystems, message in cases:
            with self.subTest(message):
                self.assertEqual(run_as(self, static_analysis, files, *ecosystems), Result.passed(message))


class CAndCxxTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, static_analysis, files)

    def test_fails_when_no_analyzer_runs(self) -> None:
        self.assertEqual(self._run(BARE_PROJECT), Result.failed("no static analyzer runs", C_HINT))

    def test_warns_when_only_one_runs(self) -> None:
        result = self._run({**CLANG_TIDY_CONFIG, **github_job("ubuntu-latest", "run-clang-tidy -p build")})
        self.assertEqual(result, Result.warned("clang-tidy (.clang-tidy) runs, but cppcheck does not run", C_HINT))

    def test_warns_when_a_clang_tidy_configuration_is_not_used(self) -> None:
        cmake = {"CMakeLists.txt": "set(CMAKE_CXX_CPPCHECK cppcheck)\n", **CONFIGURES}
        result = self._run({**CLANG_TIDY_CONFIG, **cmake})
        expected = Result.warned("cppcheck runs, but clang-tidy is configured (.clang-tidy) but does not run", C_HINT)
        self.assertEqual(result, expected)

    def test_warns_when_only_a_configuration_exists(self) -> None:
        expected = Result.warned("clang-tidy is configured (.clang-tidy) but does not run", C_HINT)
        self.assertEqual(self._run(CLANG_TIDY_CONFIG), expected)

    def test_a_cmake_variable_runs_an_analyzer_only_where_ci_configures_the_build(self) -> None:
        cmake = {"CMakeLists.txt": "set(CMAKE_CXX_CPPCHECK cppcheck)\n"}
        self.assertEqual(self._run(cmake), Result.failed("no static analyzer runs", C_HINT))
        on_the_command_line = github_job(
            "ubuntu-latest", "cmake -S . -B b -DCMAKE_CXX_CLANG_TIDY=clang-tidy && cppcheck ."
        )
        self.assertEqual(self._run({**CLANG_TIDY_CONFIG, **on_the_command_line}).status, Status.PASS)

    def test_warns_when_clang_tidy_runs_without_a_configuration(self) -> None:
        files = {
            "CMakeLists.txt": "set(CMAKE_CXX_CLANG_TIDY clang-tidy)\nset(CMAKE_CXX_CPPCHECK cppcheck)\n",
            **CONFIGURES,
        }
        expected = Result.warned(f"clang-tidy and cppcheck run, but {DEFAULTS.format('clang-tidy')}", C_HINT)
        self.assertEqual(self._run(files), expected)


class ActionAndAnswerTests(unittest.TestCase):
    def test_analyzer_actions_run_their_analyzers(self) -> None:
        workflow = {
            GITHUB_WORKFLOW: "jobs:\n  l:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: cpp-linter/cpp-linter-action@v2\n      - uses: deep5050/cppcheck-action@v3\n"
        }
        result = run_in_every_layout(self, static_analysis, {**CLANG_TIDY_CONFIG, **workflow})
        self.assertEqual(result, Result.passed("clang-tidy (.clang-tidy) and cppcheck run"))

    def test_a_language_no_known_analyzer_handles_is_skipped(self) -> None:
        answer = tool_answer(ANALYSIS, CHECKS, "Lang", Facts(()), ())
        self.assertEqual(judge_analysis(answer).status, Status.SKIP)
        typed = tool_answer(TYPE_CHECK, Strictness.CHECKS, "Lang", Facts(()), ())
        self.assertEqual(judge_type_checking(typed).message, "no known type checker handles Lang")


class PythonTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, static_analysis, files, PYTHON)

    def test_any_linter_is_enough(self) -> None:
        cases = {
            "ruff check .": "ruff check runs",
            "pylint src": "pylint runs",
            "flake8": "flake8 runs",
        }
        for command, message in cases.items():
            with self.subTest(command):
                self.assertEqual(self._run(github_job("ubuntu-latest", command)), Result.passed(message))

    def test_ruff_check_hooks_lint(self) -> None:
        hooks = (
            "ci: {}\nrepos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    hooks:\n"
            "      - id: ruff-check\n"
        )
        self.assertEqual(self._run({".pre-commit-config.yaml": hooks}), Result.passed("ruff check runs"))

    def test_ruff_format_is_not_linting(self) -> None:
        result = self._run(github_job("ubuntu-latest", "ruff format --check"))
        self.assertEqual(result, Result.failed("no static analyzer runs", PYTHON_HINT))

    def test_a_pre_commit_hook_runs_a_linter_where_pre_commit_runs(self) -> None:
        hooks = (
            "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
            "    hooks:\n      - id: ruff\n      - id: ruff-format\n"
        )
        for files in (
            {".pre-commit-config.yaml": f"ci:\n  autoupdate_schedule: monthly\n{hooks}"},
            {".pre-commit-config.yaml": hooks, **github_job("ubuntu-latest", "pre-commit run --all-files")},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files), Result.passed("ruff check runs"))
        # Hooks that nothing runs (only contributors, locally) are not CI.
        self.assertEqual(self._run({".pre-commit-config.yaml": hooks}).status, Status.FAIL)
        # pre-commit.ci skips the hooks its ci.skip names.
        skipped = {".pre-commit-config.yaml": f"ci:\n  skip: [ruff]\n{hooks}"}
        self.assertEqual(self._run(skipped).status, Status.FAIL)

    def test_warns_when_a_linter_is_configured_but_not_run(self) -> None:
        cases = {
            "pyproject.toml": ("[project]\nname = 'x'\n\n[tool.pylint.main]\njobs = 0\n", "pylint", "pyproject.toml"),
            "ruff.toml": ("line-length = 100\n", "ruff check", "ruff.toml"),
            "setup.cfg": ("[flake8]\nmax-line-length = 100\n", "flake8", "setup.cfg"),
        }
        for path, (text, linter, config) in cases.items():
            with self.subTest(path):
                expected = Result.warned(f"{linter} is configured ({config}) but does not run", PYTHON_HINT)
                self.assertEqual(self._run({path: text}), expected)

    def test_a_section_of_another_tool_is_not_a_configuration(self) -> None:
        result = self._run({"setup.cfg": "[metadata]\nname = x\n", "tox.ini": "[tox]\n"})
        self.assertEqual(result, Result.failed("no static analyzer runs", PYTHON_HINT))


class RustTests(unittest.TestCase):
    def test_clippy_runs(self) -> None:
        result = run_as(self, static_analysis, github_job("ubuntu-latest", "cargo +nightly clippy"), RUST)
        self.assertEqual(result, Result.passed("clippy runs"))

    def test_clippy_toml_configures_it(self) -> None:
        files = {"clippy.toml": "msrv = '1.80'\n", **github_job("ubuntu-latest", "cargo clippy -- -D warnings")}
        self.assertEqual(run_as(self, static_analysis, files, RUST), Result.passed("clippy (clippy.toml) runs"))

    def test_fails_without_clippy(self) -> None:
        result = run_as(self, static_analysis, github_job("ubuntu-latest", "cargo test"), RUST)
        self.assertEqual(result, Result.failed("no static analyzer runs", RUST_HINT))


class GoTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, static_analysis, files, GO)

    def test_passes_when_more_linters_are_enabled(self) -> None:
        configurations = {
            ".golangci.yml": "linters:\n  enable:\n    - revive\n",
            ".golangci.yaml": 'version: "2"\nlinters:\n  default: all\n',
            ".golangci.toml": '[linters]\nenable = ["revive"]\n',
            ".golangci.json": '{"linters": {"enable-all": true}}',
        }
        for path, text in configurations.items():
            with self.subTest(path):
                self.assertEqual(self._run({**GOLANGCI_CI, path: text}), Result.passed(f"golangci-lint ({path}) runs"))

    def test_warns_with_only_the_default_linters(self) -> None:
        expected = Result.warned(f"golangci-lint runs, but {DEFAULTS.format('golangci-lint')}", GO_HINT)
        for text in ("linters:\n  enable: []\n", 'version: "2"\nlinters:\n  default: standard\n', None):
            with self.subTest(text):
                files = GOLANGCI_CI if text is None else {**GOLANGCI_CI, ".golangci.yml": text}
                self.assertEqual(self._run(files), expected)

    def test_go_vet_and_staticcheck_are_not_enough(self) -> None:
        result = self._run(github_job("ubuntu-latest", "go vet ./...", "staticcheck ./..."))
        self.assertEqual(result.status, Status.FAIL)

    def test_the_golangci_lint_action_runs_it(self) -> None:
        files = {
            GITHUB_WORKFLOW: "jobs:\n  l:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: golangci/golangci-lint-action@v8\n"
        }
        self.assertEqual(self._run({**files, ".golangci.yml": "linters:\n  enable: [revive]\n"}).status, Status.PASS)
