import unittest

from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.c_cpp.clang_tidy import STATIC_ANALYSIS as C_AND_CXX_ANALYSIS
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.go import STATIC_ANALYSIS as GO_ANALYSIS
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.python import STATIC_ANALYSIS as PYTHON_ANALYSIS
from project_validator.ecosystems.rust import RUST
from project_validator.ecosystems.rust import STATIC_ANALYSIS as RUST_ANALYSIS
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

C_HINT = C_AND_CXX_ANALYSIS.hint
PYTHON_HINT = PYTHON_ANALYSIS.hint
GO_HINT = GO_ANALYSIS.hint
CLANG_TIDY_CONFIG = {".clang-tidy": "Checks: 'bugprone-*'\n"}
GOLANGCI_CI = github_job("ubuntu-latest", "golangci-lint run ./...")


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
        result = self._run({**CLANG_TIDY_CONFIG, "CMakeLists.txt": "set(CMAKE_CXX_CPPCHECK cppcheck)\n"})
        expected = Result.warned("cppcheck runs, but clang-tidy is configured (.clang-tidy) but does not run", C_HINT)
        self.assertEqual(result, expected)

    def test_warns_when_only_a_configuration_exists(self) -> None:
        expected = Result.warned("clang-tidy is configured (.clang-tidy) but does not run", C_HINT)
        self.assertEqual(self._run(CLANG_TIDY_CONFIG), expected)

    def test_warns_when_clang_tidy_runs_without_a_configuration(self) -> None:
        files = {"CMakeLists.txt": "set(CMAKE_CXX_CLANG_TIDY clang-tidy)\nset(CMAKE_CXX_CPPCHECK cppcheck)\n"}
        expected = Result.warned(
            "clang-tidy and cppcheck run, but clang-tidy has no .clang-tidy, so it runs only its default checks", C_HINT
        )
        self.assertEqual(self._run(files), expected)


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

    def test_ruff_format_is_not_linting(self) -> None:
        result = self._run(github_job("ubuntu-latest", "ruff format --check"))
        self.assertEqual(result, Result.failed("no static analyzer runs", PYTHON_HINT))

    def test_a_pre_commit_hook_runs_a_linter(self) -> None:
        hooks = {
            ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
            "    hooks:\n      - id: ruff\n      - id: ruff-format\n"
        }
        self.assertEqual(self._run(hooks), Result.passed("ruff check runs"))

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

    def test_fails_without_clippy(self) -> None:
        result = run_as(self, static_analysis, github_job("ubuntu-latest", "cargo test"), RUST)
        self.assertEqual(result, Result.failed("no static analyzer runs", RUST_ANALYSIS.hint))


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
        cases = {
            "linters:\n  enable: []\n": ".golangci.yml enables no linters beyond golangci-lint's defaults",
            'version: "2"\nlinters:\n  default: standard\n': (
                ".golangci.yml enables no linters beyond golangci-lint's defaults"
            ),
        }
        for text, problem in cases.items():
            with self.subTest(text):
                result = self._run({**GOLANGCI_CI, ".golangci.yml": text})
                self.assertEqual(result, Result.warned(f"golangci-lint (.golangci.yml) runs, but {problem}", GO_HINT))

    def test_warns_without_a_configuration(self) -> None:
        expected = Result.warned(
            "golangci-lint runs, but golangci-lint has no configuration, so it runs only its default linters", GO_HINT
        )
        self.assertEqual(self._run(GOLANGCI_CI), expected)

    def test_go_vet_and_staticcheck_are_not_enough(self) -> None:
        result = self._run(github_job("ubuntu-latest", "go vet ./...", "staticcheck ./..."))
        self.assertEqual(result.status, Status.FAIL)

    def test_the_golangci_lint_action_runs_it(self) -> None:
        files = {GITHUB_WORKFLOW: "jobs:\n  l:\n    steps:\n      - uses: golangci/golangci-lint-action@v8\n"}
        self.assertEqual(self._run({**files, ".golangci.yml": "linters:\n  enable: [revive]\n"}).status, Status.PASS)
