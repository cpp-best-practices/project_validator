import unittest
from pathlib import Path, PurePosixPath

from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Context, Options, Project, Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.plugins import discover
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

ROOT = Path(__file__).parent.parent.parent

BUILD_HINT = "consider ignoring the build directory (e.g. build/ and out/)"


def _run_with(test: unittest.TestCase, ignore_file: str, text: str) -> Result:
    return run_in_every_layout(test, vcs_ignore, {ignore_file: text})


class VcsIgnoreTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(vcs_ignore.languages, C_FAMILY | {"Python", "Rust"})

    def test_fails_without_an_ignore_file_in_every_layout(self) -> None:
        result = run_in_every_layout(self, vcs_ignore, NO_FILES, PROJECT_LAYOUTS)
        expected = Result.failed(
            "no version control ignore file found (.gitignore, .hgignore, .bzrignore, .fossil-settings/ignore-glob); "
            "build outputs can be committed by accident",
            "consider adding a .gitignore (or your version control system's equivalent) that ignores build outputs",
        )
        self.assertEqual(result, expected)

    def test_an_ignore_file_of_any_version_control_system_is_enough(self) -> None:
        for ignore_file in (".gitignore", ".hgignore", ".bzrignore", ".fossil-settings/ignore-glob"):
            with self.subTest(ignore_file=ignore_file):
                self.assertEqual(_run_with(self, ignore_file, "build\n").status, Status.PASS)

    def test_every_ignore_file_must_ignore_the_outputs(self) -> None:
        files = {".gitignore": "build/\n", ".hgignore": "\\.o$\n", ".bzrignore": "*.o\n"}
        expected = Result.warned(".hgignore, .bzrignore do not ignore the build directory", BUILD_HINT)
        self.assertEqual(run_in_every_layout(self, vcs_ignore, files), expected)

    def test_reports_what_each_ignore_file_ignores(self) -> None:
        result = run_in_every_layout(self, vcs_ignore, {".gitignore": "/build/\n", ".hgignore": "^build/\n"})
        self.assertEqual(result, Result.passed(".gitignore ignores /build/; .hgignore ignores ^build/"))

    def test_well_configured_project_passes(self) -> None:
        self.assertEqual(run_in_every_layout(self, vcs_ignore, WELL_CONFIGURED).status, Status.PASS)

    def test_this_project_ignores_its_own_build_outputs(self) -> None:
        project = Project(ROOT, frozenset({PurePosixPath("tests/fixtures")}))
        result = vcs_ignore.run(Context(project, discover().providers, Options()))
        self.assertEqual(result.status, Status.PASS, result)


class GitignoreTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return _run_with(self, ".gitignore", text)

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
        expected = Result.warned(".gitignore does not ignore the build directory", BUILD_HINT)
        self.assertEqual(self._run("*.o\n.vscode/\n"), expected)

    def test_comments_and_negations_do_not_count(self) -> None:
        for text in ("# build/\n", "!build/\n", "\\#build/\n"):
            with self.subTest(text=text):
                self.assertEqual(self._run(text).status, Status.WARN)

    def test_names_that_only_start_like_a_build_directory_do_not_count(self) -> None:
        for entry in ("buildbot.cfg", "output.txt", "src/build/", "outline/"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n").status, Status.WARN)


class HgignoreTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return _run_with(self, ".hgignore", text)

    def test_entries_are_regular_expressions_by_default(self) -> None:
        for entry in ("^build/", "^build$", "^build(/|$)", "(^|/)out/", "^cmake-build-", "build"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"# build outputs\n{entry}\n"), Result.passed(f".hgignore ignores {entry}"))

    def test_regular_expressions_that_match_no_build_directory_do_not_count(self) -> None:
        for entry in ("\\.o$", "^src/build/", "^builds/", "(unclosed"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n").status, Status.WARN)

    def test_a_syntax_line_switches_the_syntax_of_the_lines_that_follow(self) -> None:
        self.assertEqual(self._run("syntax: glob\nbuild/\n"), Result.passed(".hgignore ignores build/"))
        self.assertEqual(self._run("syntax: glob\n^build/\n").status, Status.WARN)
        self.assertEqual(
            self._run("syntax: glob\n*.o\nsyntax: regexp\n^out/\n"), Result.passed(".hgignore ignores ^out/")
        )

    def test_a_prefix_names_the_syntax_of_its_entry(self) -> None:
        for entry in ("glob:build/", "relglob:build", "rootglob:build", "path:build", "re:^build/", "regexp:^out$"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"syntax: glob\n{entry}\n"), Result.passed(f".hgignore ignores {entry}"))

    def test_rooted_globs_ignore_only_the_top_level(self) -> None:
        self.assertEqual(self._run("rootglob:src/build\n").status, Status.WARN)

    def test_included_files_and_unknown_syntaxes_are_not_followed(self) -> None:
        for text in ("include:build\n", "subinclude:build/.hgignore\n", "syntax: unknown\nbuild\n"):
            with self.subTest(text=text):
                self.assertEqual(self._run(text).status, Status.WARN)

    def test_python_and_rust_outputs_can_be_ignored_by_regular_expressions(self) -> None:
        python = run_as(self, vcs_ignore, {".hgignore": "\\.py[cod]$\n"}, PYTHON)
        self.assertEqual(python, Result.passed(".hgignore ignores \\.py[cod]$"))
        rust = run_as(self, vcs_ignore, {".hgignore": "^target/\n"}, RUST)
        self.assertEqual(rust, Result.passed(".hgignore ignores ^target/"))


class BzrignoreTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return _run_with(self, ".bzrignore", text)

    def test_passes_when_the_build_directory_is_ignored(self) -> None:
        for entry in ("build", "./build", "out/", "!!build", "RE:^build$", "re:(^|/)out"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"# build outputs\n{entry}\n"), Result.passed(f".bzrignore ignores {entry}"))

    def test_exceptions_comments_and_other_paths_do_not_count(self) -> None:
        for entry in ("!build", "# build", "./src/build", "RE:^src/build"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n").status, Status.WARN)


class FossilIgnoreGlobTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return _run_with(self, ".fossil-settings/ignore-glob", text)

    def test_globs_are_separated_by_commas_or_whitespace_and_may_be_quoted(self) -> None:
        for text in ("build/*\n", "*.o, build/*\n", "*.o out/*", '"build/*"\n', "'out'\n"):
            with self.subTest(text=text):
                self.assertEqual(self._run(text).status, Status.PASS)

    def test_reports_the_glob_that_ignores_the_build_directory(self) -> None:
        result = self._run("*.o,build/*\n")
        self.assertEqual(result, Result.passed(".fossil-settings/ignore-glob ignores build/*"))

    def test_warns_when_the_build_directory_is_not_ignored(self) -> None:
        expected = Result.warned(".fossil-settings/ignore-glob does not ignore the build directory", BUILD_HINT)
        self.assertEqual(self._run("*.o, src/build/*\n"), expected)


class PythonVcsIgnoreTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return run_as(self, vcs_ignore, {".gitignore": text}, PYTHON)

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
        self.assertEqual(run_as(self, vcs_ignore, dict(WELL_CONFIGURED_PYTHON), PYTHON).status, Status.PASS)


class RustVcsIgnoreTests(unittest.TestCase):
    def _run(self, text: str) -> Result:
        return run_as(self, vcs_ignore, {".gitignore": text}, RUST)

    def test_passes_when_the_target_directory_is_ignored(self) -> None:
        for entry in ("target", "/target", "target/", "/target/", "**/target/"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(f"{entry}\n"), Result.passed(f".gitignore ignores {entry}"))

    def test_warns_when_the_target_directory_is_not_ignored(self) -> None:
        expected = Result.warned(".gitignore does not ignore the target directory", "consider ignoring /target")
        self.assertEqual(self._run("build/\ntargets.txt\n"), expected)

    def test_well_configured_rust_project_passes(self) -> None:
        self.assertEqual(run_as(self, vcs_ignore, dict(WELL_CONFIGURED_RUST), RUST).status, Status.PASS)


class MixedLanguageVcsIgnoreTests(unittest.TestCase):
    def test_every_language_needs_its_outputs_ignored_and_findings_are_labelled(self) -> None:
        result = run_as(self, vcs_ignore, {".gitignore": "build/\n"}, C_AND_CXX, PYTHON)
        expected = Result.warned(
            "C/C++: .gitignore ignores build/; Python: .gitignore does not ignore Python bytecode",
            "Python: consider ignoring __pycache__/ and *.py[cod]",
        )
        self.assertEqual(result, expected)

    def test_passes_when_every_language_is_ignored(self) -> None:
        result = run_as(self, vcs_ignore, {".gitignore": "build/\n__pycache__/\n"}, C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.PASS)
