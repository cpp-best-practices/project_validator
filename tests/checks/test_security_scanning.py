import unittest

from project_validator.checks.security_scanning import security_scanning
from project_validator.core import Result, Status
from project_validator.ecosystems import ecosystems_for, rules_of
from project_validator.rules import SecurityLints
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED,
    ProjectLayout,
    make_context,
    run_in_every_layout,
    temp_project,
)

# Layouts of languages with no security lints of their own, which only CodeQL or GitLab SAST can scan.
UNLINTED_LAYOUTS = tuple(
    layout for layout in PROJECT_LAYOUTS if not ecosystems_for(layout.languages, rules_of(SecurityLints))
)


def _layouts_of(*languages: str) -> tuple[ProjectLayout, ...]:
    return tuple(layout for layout in PROJECT_LAYOUTS if layout.languages == frozenset(languages))


class SecurityScanningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, security_scanning, files, UNLINTED_LAYOUTS)

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(security_scanning.languages, frozenset())

    def test_warns_without_ci(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.WARN)

    def test_warns_when_ci_runs_no_code_scanning(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "steps:\n  - run: ctest --test-dir build\n"})
                self.assertEqual(result.status, Status.WARN)
                self.assertIn("no code security scanning", result.message)

    def test_passes_with_codeql_in_every_layout(self) -> None:
        result = run_in_every_layout(self, security_scanning, WELL_CONFIGURED, PROJECT_LAYOUTS)
        self.assertEqual(result, Result.passed("CI runs code security scanning with CodeQL"))

    def test_passes_with_the_gitlab_sast_template(self) -> None:
        result = self._run({".gitlab-ci.yml": "include:\n  - template: Security/SAST.gitlab-ci.yml\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.message, "CI runs code security scanning with GitLab SAST")

    def test_codeql_outside_ci_does_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "# uses: github/codeql-action/analyze@v3\n"})
        self.assertEqual(result.status, Status.WARN)


class SecurityLintTests(unittest.TestCase):
    def _run(self, files: dict[str, str], *languages: str) -> Result:
        layouts = _layouts_of(*languages)
        self.assertTrue(layouts, languages)
        return run_in_every_layout(self, security_scanning, files, layouts)

    def test_python_security_lints_in_any_spelling_count(self) -> None:
        spellings = {
            "bandit": {GITHUB_WORKFLOW: "run: python -m bandit -r src\n"},
            "bandit action": {GITHUB_WORKFLOW: "uses: PyCQA/bandit-action@v1\n"},
            "pre-commit bandit": {".pre-commit-config.yaml": "repos:\n  - hooks:\n      - id: bandit\n"},
            "ruff --select": {GITHUB_WORKFLOW: "run: ruff check --select E,S .\n"},
            "ruff --extend-select": {GITHUB_WORKFLOW: "run: ruff check --extend-select=S603 .\n"},
            "pyproject select": {"pyproject.toml": '[tool.ruff.lint]\nselect = ["E", "S"]\n'},
            "pyproject ALL": {"pyproject.toml": "[tool.ruff.lint]\nselect = ['ALL']\n"},
            "ruff.toml extend-select": {"ruff.toml": '[lint]\nextend-select = ["S"]\n'},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                result = self._run(files, "Python")
                self.assertEqual(result, Result.passed("security lints are enabled: bandit security lints"))

    def test_python_lints_without_security_rules_do_not_count(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: pip install bandit ruff && ruff check --select SIM\n"}, "Python")
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("Python: bandit security lints", result.details[-1])

    def test_forbidding_unsafe_rust_in_any_spelling_counts(self) -> None:
        spellings = {
            "Cargo lints": {"Cargo.toml": '[lints.rust]\nunsafe_code = "forbid"\n'},
            "Cargo lint table": {"Cargo.toml": "[lints.rust]\nunsafe_code = { level = 'deny' }\n"},
            "workspace member": {"crates/core/Cargo.toml": "[lints.rust]\nunsafe_code = 'forbid'\n"},
            "crate attribute": {"src/main.rs": "#![forbid(unsafe_code)]\n"},
            "library attribute": {"src/lib.rs": "#![deny(missing_docs, unsafe_code)]\n"},
            "rustflags": {".cargo/config.toml": '[build]\nrustflags = ["-F", "unsafe_code"]\n'},
            "command line": {GITHUB_WORKFLOW: "run: cargo rustc -- --forbid unsafe_code\n"},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                result = self._run(files, "Rust")
                self.assertEqual(result, Result.passed("security lints are enabled: unsafe_code forbidden"))

    def test_module_level_or_allowed_unsafe_code_does_not_count(self) -> None:
        for files in (
            {"src/lib.rs": "#[forbid(unsafe_code)]\nmod safe {}\n"},
            {"Cargo.toml": "[lints.rust]\nunsafe_code = 'allow'\n"},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files, "Rust").status, Status.WARN)

    def test_go_security_lints(self) -> None:
        for command in ("gosec ./...", "uses: securego/gosec@master"):
            with self.subTest(command):
                result = self._run({GITHUB_WORKFLOW: f"steps:\n  - {command}\n"}, "Go")
                self.assertEqual(result, Result.passed("security lints are enabled: gosec"))

    def test_a_language_without_security_lints_is_only_scanned_by_codeql(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: bandit -r python\n"}, "C", "C++", "Python")
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "no code security scanning for C/C++")
        self.assertEqual(result.details[0], "found bandit security lints")

    def test_lints_of_several_languages_are_labelled(self) -> None:
        files = {
            "pyproject.toml": "",
            "app/__init__.py": "",
            "go.mod": "module example.com/app\n",
            "main.go": "package main\n",
            GITHUB_WORKFLOW: "steps:\n  - run: bandit -r app\n  - run: gosec ./...\n",
        }
        with temp_project(files) as root:
            result = security_scanning.run(make_context(root))
        self.assertEqual(result, Result.passed("security lints are enabled: Python: bandit security lints; Go: gosec"))
