import unittest

from project_validator.checks.gitignore import gitignore
from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    NO_FILES,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)


class GitignoreTests(unittest.TestCase):
    BUILD_HINT = "consider ignoring the build directory (e.g. build/ and out/)"

    def _run(self, gitignore_text: str) -> Result:
        return run_in_every_layout(self, gitignore, {".gitignore": gitignore_text})

    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(gitignore.languages, C_FAMILY | {"Python", "Rust"})

    def test_fails_without_a_gitignore_in_every_layout(self) -> None:
        result = run_in_every_layout(self, gitignore, NO_FILES, PROJECT_LAYOUTS)
        expected = Result.failed(
            "no .gitignore found; build outputs can be committed by accident",
            "consider adding a .gitignore that ignores build outputs",
        )
        self.assertEqual(result, expected)

    def test_passes_when_the_build_directory_is_ignored(self) -> None:
        entries = (
            "build",
            "build/",
            "/build/",
            "**/build/",
            "build*/",
            "build-*/",
            "[Bb]uild/",
            "Build/",
            "_build/",
            "out/",
            "/out",
            "cmake-build-*/",
            "cmake-build-debug",
            "build/*",
            "build/**",
        )
        for entry in entries:
            with self.subTest(entry=entry):
                result = self._run(f"# build outputs\n\n  {entry}  \n")
                self.assertEqual(result, Result.passed(f".gitignore ignores {entry}"))

    def test_reports_the_first_ignored_build_directory(self) -> None:
        result = self._run("*.o\n/build/\nout/\n")
        self.assertEqual(result, Result.passed(".gitignore ignores /build/"))

    def test_warns_when_the_build_directory_is_not_ignored(self) -> None:
        result = self._run("*.o\n.vscode/\n")
        expected = Result.warned(".gitignore does not ignore the build directory", self.BUILD_HINT)
        self.assertEqual(result, expected)

    def test_comments_and_negations_do_not_count(self) -> None:
        for text in ("# build/\n", "!build/\n", "\\#build/\n"):
            with self.subTest(text=text):
                self.assertEqual(self._run(text).status, Status.WARN)

    def test_names_that_only_start_like_a_build_directory_do_not_count(self) -> None:
        for entry in ("buildbot.cfg", "output.txt", "src/build/", "outline/"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n").status, Status.WARN)

    def test_well_configured_project_passes(self) -> None:
        self.assertEqual(run_in_every_layout(self, gitignore, WELL_CONFIGURED).status, Status.PASS)


class PythonGitignoreTests(unittest.TestCase):
    def _run(self, gitignore_text: str) -> Result:
        return run_as(self, gitignore, {".gitignore": gitignore_text}, PYTHON)

    def test_passes_when_bytecode_is_ignored(self) -> None:
        for entry in ("__pycache__/", "__pycache__", "**/__pycache__/", "*.pyc", "*.py[cod]", "*.py[co]"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n"), Result.passed(f".gitignore ignores {entry}"))

    def test_warns_when_bytecode_is_not_ignored(self) -> None:
        expected = Result.warned(
            ".gitignore does not ignore Python bytecode", "consider ignoring __pycache__/ and *.py[cod]"
        )
        self.assertEqual(self._run("build/\n.venv/\n"), expected)

    def test_well_configured_python_project_passes(self) -> None:
        self.assertEqual(run_as(self, gitignore, dict(WELL_CONFIGURED_PYTHON), PYTHON).status, Status.PASS)


class RustGitignoreTests(unittest.TestCase):
    def _run(self, gitignore_text: str) -> Result:
        return run_as(self, gitignore, {".gitignore": gitignore_text}, RUST)

    def test_passes_when_the_target_directory_is_ignored(self) -> None:
        for entry in ("target", "/target", "target/", "/target/", "**/target/"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n"), Result.passed(f".gitignore ignores {entry}"))

    def test_warns_when_the_target_directory_is_not_ignored(self) -> None:
        expected = Result.warned(".gitignore does not ignore the target directory", "consider ignoring /target")
        self.assertEqual(self._run("build/\ntargets.txt\n"), expected)

    def test_well_configured_rust_project_passes(self) -> None:
        self.assertEqual(run_as(self, gitignore, dict(WELL_CONFIGURED_RUST), RUST).status, Status.PASS)


class MixedLanguageGitignoreTests(unittest.TestCase):
    def test_every_language_needs_its_outputs_ignored_and_findings_are_labelled(self) -> None:
        result = run_as(self, gitignore, {".gitignore": "build/\n"}, C_AND_CXX, PYTHON)
        expected = Result.warned(
            "C/C++: .gitignore ignores build/; Python: .gitignore does not ignore Python bytecode",
            "Python: consider ignoring __pycache__/ and *.py[cod]",
        )
        self.assertEqual(result, expected)

    def test_passes_when_every_language_is_ignored(self) -> None:
        result = run_as(self, gitignore, {".gitignore": "build/\n__pycache__/\n"}, C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.PASS)
