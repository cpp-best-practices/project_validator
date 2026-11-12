from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.security_scanning import security_scanning
from project_validator.core import Result, Status
from project_validator.facts import Facts
from project_validator.facts.security import SCANS, SECURITY
from project_validator.policy.security import judge_security
from project_validator.questions.tooling import tool_answer
from tests.layouts.model import ProjectLayout
from tests.support import (
    BARE_PROJECT,
    GITHUB_WORKFLOW,
    PROJECT_LAYOUTS,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    make_context,
    run_in_every_layout,
    temp_project,
)

C_HINT = (
    "consider running in CI: CodeQL (github/codeql-action), GitLab SAST (Security/SAST.gitlab-ci.yml) or semgrep ci"
)


def _layouts_of(*languages: str) -> tuple[ProjectLayout, ...]:
    return tuple(layout for layout in PROJECT_LAYOUTS if layout.languages | layout.formats == frozenset(languages))


def _steps(*steps: Mapping[str, object]) -> dict[str, str]:
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"scan": {"runs-on": "ubuntu-latest", "steps": list(steps)}}})}


def _found(*tools: str) -> Result:
    return Result.passed(f"CI scans the code for security problems with {', '.join(tools)}")


class SecurityScanningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(
            self, security_scanning, files, c_family_layouts_built_with(security_scanning, "CMake")
        )

    def test_applies_to_the_languages_its_scanners_handle(self) -> None:
        self.assertLessEqual({"C", "C++", "Python", "Go", "Rust"}, security_scanning.languages)

    def test_warns_without_ci(self) -> None:
        self.assertEqual(
            self._run(BARE_PROJECT), Result.warned("no code security scanning found in CI configuration", C_HINT)
        )

    def test_passes_with_codeql_in_every_layout(self) -> None:
        # CodeQL does not analyse PHP, Terraform's HCL, Elixir, Scala, Dart, Lua, OCaml, Julia, Clojure or Dockerfiles
        # (nothing scans Erlang or Haskell: skipped).
        unread = {
            "PHP": "PHP",
            "Terraform": "Terraform",
            "Elixir": "BEAM",
            "Scala": "Scala",
            "Dart": "Dart",
            "Lua": "Lua",
            "OCaml": "OCaml",
            "Julia": "Julia",
            "Clojure": "Clojure",
            "Dockerfile": "Docker",
        }
        layouts = tuple(layout for layout in PROJECT_LAYOUTS if not (layout.languages | layout.formats) & unread.keys())
        self.assertEqual(run_in_every_layout(self, security_scanning, WELL_CONFIGURED, layouts), _found("CodeQL"))
        for language, label in unread.items():
            result = run_in_every_layout(self, security_scanning, WELL_CONFIGURED, _layouts_of(language))
            self.assertIn(f"{label}: no code security scanning found in CI configuration", result.message)

    def test_multi_language_scanners(self) -> None:
        for files, tool in (
            (_steps({"uses": "github/codeql-action/analyze@v3"}), "CodeQL"),
            ({".gitlab-ci.yml": "include:\n  - template: Security/SAST.gitlab-ci.yml\n"}, "GitLab SAST"),
            ({".gitlab-ci.yml": "include:\n  - template: Jobs/SAST.latest.gitlab-ci.yml\n"}, "GitLab SAST"),
            (github_job("x", "semgrep ci"), "semgrep"),
            (_steps({"uses": "returntocorp/semgrep-action@v1"}), "semgrep"),
        ):
            with self.subTest(tool=tool, files=files):
                self.assertEqual(self._run(files), _found(tool))

    def test_codeql_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# uses: github/codeql-action/analyze@v3\n"})
        self.assertEqual(result.status, Status.WARN)

    def test_what_ci_configuration_that_is_not_parsed_hides_is_an_error(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "ctest"))
                self.assertEqual(result.status, Status.ERROR)

    def test_a_language_no_known_scanner_handles_is_skipped(self) -> None:
        answer = tool_answer(SECURITY, SCANS, "Lang", Facts(()), ())
        self.assertEqual(judge_security(answer).status, Status.SKIP)


class SecurityLintTests(unittest.TestCase):
    def _run(self, files: dict[str, str], *languages: str) -> Result:
        layouts = _layouts_of(*languages)
        self.assertTrue(layouts, languages)
        return run_in_every_layout(self, security_scanning, files, layouts)

    def test_python_security_lints_in_any_spelling_count(self) -> None:
        ruff = github_job("x", "ruff check .")
        spellings = {
            "bandit": (github_job("x", "python -m bandit -r src"), "bandit"),
            "bandit action": (_steps({"uses": "PyCQA/bandit-action@v1"}), "bandit"),
            "pre-commit bandit": (
                {
                    ".pre-commit-config.yaml": "ci: {}\nrepos:\n  - repo: https://github.com/PyCQA/bandit\n"
                    "    hooks:\n      - id: bandit\n"
                },
                "bandit",
            ),
            "ruff --select": (github_job("x", "ruff check --select E,S ."), "ruff's bandit rules"),
            "ruff --extend-select": (github_job("x", "ruff check --extend-select=S603 ."), "ruff's bandit rules"),
            "pyproject select": (
                {"pyproject.toml": '[tool.ruff.lint]\nselect = ["E", "S"]\n', **ruff},
                "ruff's bandit rules",
            ),
            "pyproject ALL": (
                {"pyproject.toml": "[tool.ruff.lint]\nselect = ['ALL']\n", **ruff},
                "ruff's bandit rules",
            ),
            "ruff.toml extend-select": (
                {"ruff.toml": '[lint]\nextend-select = ["S"]\n', **ruff},
                "ruff's bandit rules",
            ),
        }
        for spelling, (files, tool) in spellings.items():
            with self.subTest(spelling):
                self.assertEqual(self._run(files, "Python"), _found(tool))

    def test_python_lints_without_security_rules_do_not_count(self) -> None:
        result = self._run(github_job("x", "pip install bandit ruff && ruff check --select SIM"), "Python")
        self.assertEqual(result.status, Status.WARN)
        # A selection in settings counts where CI runs ruff check.
        self.assertEqual(
            self._run({"pyproject.toml": "[tool.ruff.lint]\nselect = ['S']\n"}, "Python").status, Status.WARN
        )

    def test_forbidding_unsafe_rust_in_any_spelling_counts_where_cargo_builds(self) -> None:
        build = github_job("x", "cargo build")
        spellings = {
            "Cargo lints": {"Cargo.toml": '[lints.rust]\nunsafe_code = "forbid"\n'},
            "Cargo lint table": {"Cargo.toml": "[lints.rust]\nunsafe_code = { level = 'deny' }\n"},
            "workspace lints": {"Cargo.toml": "[workspace.lints.rust]\nunsafe_code = 'forbid'\n"},
            "crate attribute": {"src/main.rs": "#![forbid(unsafe_code)]\n"},
            "library attribute": {"src/lib.rs": "#![deny(missing_docs, unsafe_code)]\n"},
            "rustflags": {".cargo/config.toml": '[build]\nrustflags = ["-F", "unsafe_code"]\n'},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                self.assertEqual(self._run({**files, **build}, "Rust"), _found("unsafe_code forbidden"))
        for command in ("cargo rustc -- --forbid unsafe_code", "RUSTFLAGS='-D unsafe_code' cargo test"):
            with self.subTest(command):
                self.assertEqual(self._run(github_job("x", command), "Rust"), _found("unsafe_code forbidden"))

    def test_module_level_or_allowed_unsafe_code_does_not_count(self) -> None:
        build = github_job("x", "cargo build")
        for files in (
            {"src/lib.rs": "#[forbid(unsafe_code)]\nmod safe {}\n", **build},
            {"Cargo.toml": "[lints.rust]\nunsafe_code = 'allow'\n", **build},
            {"Cargo.toml": "[lints.rust]\nunsafe_code = 'forbid'\n"},
            {".cargo/config.toml": '[build]\nrustflags = ["-D", "warnings"]\n', **build},
            {".cargo/config.toml": "[build\n", **build},
        ):
            with self.subTest(files=files):
                self.assertNotEqual(self._run(files, "Rust").status, Status.PASS)

    def test_go_security_lints(self) -> None:
        golangci = {".golangci.yml": "linters:\n  enable: [gosec]\n", **github_job("x", "golangci-lint run")}
        for files, tool in (
            (github_job("x", "gosec ./..."), "gosec"),
            (_steps({"uses": "securego/gosec@master"}), "gosec"),
            (golangci, "golangci-lint's gosec"),
            (
                {".golangci.yml": "linters:\n  default: all\n", **github_job("x", "golangci-lint run")},
                "golangci-lint's gosec",
            ),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files, "Go"), _found(tool))
        without = {".golangci.yml": "linters:\n  enable: [revive]\n", **github_job("x", "golangci-lint run")}
        self.assertEqual(self._run(without, "Go").status, Status.WARN)

    def test_each_language_is_judged_and_findings_are_labelled(self) -> None:
        result = self._run(github_job("x", "bandit -r python"), "C", "C++", "Python")
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(
            result.message,
            "C/C++: no code security scanning found in CI configuration; Python: CI scans the code for security "
            "problems with bandit",
        )

    def test_lints_of_several_languages_are_labelled(self) -> None:
        files = {
            "pyproject.toml": "",
            "app/__init__.py": "",
            "go.mod": "module example.com/app\n",
            "main.go": "package main\n",
            **github_job("x", "bandit -r app", "gosec ./..."),
        }
        with temp_project(files) as root:
            result = security_scanning.run(make_context(root))
        self.assertEqual(
            result,
            Result.passed(
                "Go: CI scans the code for security problems with gosec; "
                "Python: CI scans the code for security problems with bandit"
            ),
        )
