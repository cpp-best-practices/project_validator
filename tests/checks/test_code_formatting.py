import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)


class CodeFormattingTests(unittest.TestCase):
    CLANG_FORMAT_HINT = (
        "consider a CI job that checks formatting (clang-format --dry-run -Werror) or applies it automatically"
    )

    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, code_formatting, files)

    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(code_formatting.languages, C_FAMILY | {"Python", "Rust"})

    def test_fails_without_a_clang_format_file(self) -> None:
        result = self._run(BARE_PROJECT)
        expected = Result.failed(
            "no clang-format configuration found; formatting is not defined", self.CLANG_FORMAT_HINT
        )
        self.assertEqual(result, expected)

    def test_passes_when_ci_checks_formatting(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result, Result.passed(".clang-format is defined and CI runs clang-format"))

    def test_passes_with_a_clang_format_github_action(self) -> None:
        result = self._run(
            {
                "_clang-format": "BasedOnStyle: LLVM\n",
                ".github/workflows/format.yml": "steps:\n  - uses: DoozyX/clang-format-lint-action@v0.18\n",
            }
        )
        self.assertEqual(result, Result.passed("_clang-format is defined and CI runs clang-format"))

    def test_git_clang_format_in_any_ci_passes(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({".clang-format": "BasedOnStyle: LLVM\n", path: "script: git clang-format --diff\n"})
                self.assertEqual(result.status, Status.PASS)

    def test_warns_when_ci_does_not_run_clang_format(self) -> None:
        result = self._run(
            {
                ".clang-format": "BasedOnStyle: LLVM\n",
                GITHUB_WORKFLOW: "steps:\n  - run: cmake -S . -B build\n",
            }
        )
        expected = Result.warned(".clang-format is defined but CI does not run clang-format", self.CLANG_FORMAT_HINT)
        self.assertEqual(result, expected)

    def test_mentioning_the_config_file_in_ci_does_not_count(self) -> None:
        result = self._run(
            {
                ".clang-format": "BasedOnStyle: LLVM\n",
                GITHUB_WORKFLOW: "on:\n  push:\n    paths-ignore: ['.clang-format', '_clang-format']\n",
            }
        )
        self.assertEqual(result.status, Status.WARN)

    def test_running_clang_format_without_a_config_file_fails(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "steps:\n  - run: clang-format --dry-run -Werror src/*.cpp\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_python_and_rust_formatters_do_not_count(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: ruff format --check && cargo fmt --check\n"})
        self.assertEqual(result.status, Status.FAIL)


class PythonCodeFormattingTests(unittest.TestCase):
    HINT = "consider a CI job that runs ruff format --check (or black --check)"

    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, code_formatting, files, PYTHON)

    def test_formatter_in_any_ci_passes_with_its_default_style(self) -> None:
        commands = {
            "ruff format": "ruff format --check .",
            "black": "python -m black src tests --check",
        }
        for provider, path in CI_FILES.items():
            for tool, command in commands.items():
                with self.subTest(ci=provider, tool=tool):
                    result = self._run({path: f"script: {command}\n"})
                    self.assertEqual(result, Result.passed(f"CI enforces the {tool} style"))

    def test_black_github_action_passes(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "steps:\n  - uses: psf/black@stable\n"})
        self.assertEqual(result, Result.passed("CI enforces the black style"))

    def test_configured_formatter_is_reported(self) -> None:
        configurations = {
            "pyproject.toml": "[project]\nname = 'app'\n\n[tool.ruff.format]\nquote-style = 'double'\n",
            "ruff.toml": "line-length = 120\n",
            ".ruff.toml": "line-length = 120\n",
        }
        for name, text in configurations.items():
            with self.subTest(name):
                result = self._run({name: text, GITHUB_WORKFLOW: "run: ruff format --diff\n"})
                self.assertEqual(result, Result.passed(f"{name} is defined and CI runs ruff format"))

    def test_warns_when_configured_but_ci_does_not_format(self) -> None:
        result = self._run({"pyproject.toml": "[tool.black]\nline-length = 100\n", GITHUB_WORKFLOW: "run: pytest\n"})
        self.assertEqual(
            result, Result.warned("pyproject.toml is defined but CI does not run ruff format or black", self.HINT)
        )

    def test_fails_without_a_formatter(self) -> None:
        result = self._run({"pyproject.toml": "[project]\nname = 'black'\n", GITHUB_WORKFLOW: "run: black-box-tests\n"})
        expected = Result.failed("no ruff format or black configuration found; formatting is not defined", self.HINT)
        self.assertEqual(result, expected)

    def test_black_that_only_rewrites_files_does_not_count(self) -> None:
        self.assertEqual(self._run({GITHUB_WORKFLOW: "run: black .\n"}).status, Status.FAIL)

    def test_clang_format_does_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)

    def test_well_configured_python_project_passes(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_PYTHON)).status, Status.PASS)


class RustCodeFormattingTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, code_formatting, files, RUST)

    def test_rustfmt_in_any_ci_passes_with_its_default_style(self) -> None:
        commands = ("cargo fmt --all -- --check", "cargo +nightly fmt --check", "rustfmt --check src/lib.rs")
        for provider, path in CI_FILES.items():
            for command in commands:
                with self.subTest(ci=provider, command=command):
                    result = self._run({path: f"script: {command}\n"})
                    self.assertEqual(result, Result.passed("CI enforces the rustfmt style"))

    def test_configured_rustfmt_is_reported(self) -> None:
        for name in ("rustfmt.toml", ".rustfmt.toml"):
            with self.subTest(name):
                result = self._run({name: "max_width = 120\n", GITHUB_WORKFLOW: "run: cargo fmt --check\n"})
                self.assertEqual(result, Result.passed(f"{name} is defined and CI runs rustfmt"))

    def test_warns_when_ci_only_mentions_the_config_file(self) -> None:
        result = self._run({"rustfmt.toml": "edition = '2024'\n", GITHUB_WORKFLOW: "paths: ['rustfmt.toml']\n"})
        expected = Result.warned(
            "rustfmt.toml is defined but CI does not run rustfmt", "consider a CI job that runs cargo fmt --check"
        )
        self.assertEqual(result, expected)

    def test_fails_without_rustfmt(self) -> None:
        self.assertEqual(self._run({GITHUB_WORKFLOW: "run: cargo test\n"}).status, Status.FAIL)

    def test_well_configured_rust_project_passes(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_RUST)).status, Status.PASS)


class MixedLanguageCodeFormattingTests(unittest.TestCase):
    def test_every_language_needs_a_formatter_and_findings_are_labelled(self) -> None:
        result = run_as(self, code_formatting, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(
            result,
            Result.failed(
                "C/C++: .clang-format is defined and CI runs clang-format; "
                "Python: no ruff format or black configuration found; formatting is not defined",
                "Python: consider a CI job that runs ruff format --check (or black --check)",
            ),
        )

    def test_passes_when_every_language_is_formatted(self) -> None:
        workflow = WELL_CONFIGURED[GITHUB_WORKFLOW] + "      - run: ruff format --check\n"
        result = run_as(self, code_formatting, {**WELL_CONFIGURED, GITHUB_WORKFLOW: workflow}, C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.PASS)
