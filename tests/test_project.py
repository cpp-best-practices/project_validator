from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from unittest import mock

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.core import Project, Status
from project_validator.facts import Unknown
from tests.support import PROJECT_LAYOUTS, layout_project, make_context, temp_project


class ProjectTests(unittest.TestCase):
    def test_a_file_exists_only_spelled_as_it_is(self) -> None:
        with temp_project({"Makefile": ""}) as root:
            project = Project(root)
            self.assertEqual(
                (project.exists("Makefile"), project.exists("makefile"), project.exists("x")), (True, False, False)
            )

    def test_finds_cmake_files_recursively(self) -> None:
        files = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "cmake/Warnings.cmake": "", "src/main.cpp": ""}
        with temp_project(files) as root:
            self.assertEqual(
                Project(root).cmake_files(), ["CMakeLists.txt", "cmake/Warnings.cmake", "src/CMakeLists.txt"]
            )

    def test_a_project_is_read_as_it_was_first_listed(self) -> None:
        """The tree is walked once: extractors ask for the files many times, and a project does not change under a
        run."""
        with temp_project({"src/main.c": ""}) as root:
            project = Project(root)
            self.assertEqual((project.files(), project.tracked_files()), (["src/main.c"], ["src/main.c"]))
            (root / "src" / "later.c").write_text("")
            self.assertEqual((project.files(), project.tracked_files()), (["src/main.c"], ["src/main.c"]))

    def test_lists_every_file_of_every_layout(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                self.assertEqual(Project(root).files(), sorted(layout.files))

    def test_every_layout_skips_hidden_vendored_and_build_directories(self) -> None:
        skipped = {
            ".git/HEAD": "",
            ".venv/lib/x.py": "",
            "node_modules/y/y.cpp": "",
            "__pycache__/z.py": "",
            "build/CMakeCache.txt": "",
            "build/_deps/x/x.c": "",
            "out/CACHEDIR.TAG": "",
            "out/debug/x.rs": "",
        }
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, skipped) as root:
                self.assertEqual(Project(root).files(), sorted(layout.files))

    def test_skips_hidden_directories_and_build_trees(self) -> None:
        files = {
            "CMakeLists.txt": "",
            ".git/CMakeLists.txt": "",
            "out/CMakeCache.txt": "",
            "out/_deps/x/CMakeLists.txt": "",
        }
        with temp_project(files) as root:
            self.assertEqual(Project(root).cmake_files(), ["CMakeLists.txt"])

    def test_skips_excluded_directories(self) -> None:
        files = {"CMakeLists.txt": "", "tests/fixtures/x/CMakeLists.txt": "", "tests/CMakeLists.txt": ""}
        with temp_project(files) as root:
            project = Project(root, frozenset({PurePosixPath("tests/fixtures")}))
            self.assertEqual(project.cmake_files(), ["CMakeLists.txt", "tests/CMakeLists.txt"])

    def test_files_in_filters_by_suffix_and_ignores_missing_directories(self) -> None:
        files = {"w/a.yml": "", "w/b.yaml": "", "w/c.txt": ""}
        with temp_project(files) as root:
            project = Project(root)
            self.assertEqual(project.files_in("w", (".yml", ".yaml")), ["w/a.yml", "w/b.yaml"])
            self.assertEqual(project.files_in("missing", (".yml",)), [])


def git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)  # noqa: S603, S607 - tests


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TrackedFilesTests(unittest.TestCase):
    def test_lists_the_files_git_tracks(self) -> None:
        files = {"src/main.c": "", ".github/workflows/ci.yml": "", "untracked.c": "", "tests/fixtures/f.c": ""}
        with temp_project(files) as root:
            git(root, "init", "-q")
            git(root, "add", "src", ".github", "tests")
            project = Project(root, frozenset({PurePosixPath("tests/fixtures")}))
            self.assertEqual(project.tracked_files(), [".github/workflows/ci.yml", "src/main.c"])

    def test_lists_every_file_outside_a_git_checkout(self) -> None:
        with temp_project({"src/main.c": "", ".github/ci.yml": ""}) as root:
            self.assertEqual(Project(root).tracked_files(), ["src/main.c"])
            with mock.patch("shutil.which", return_value=None):
                self.assertEqual(Project(root).tracked_files(), ["src/main.c"])

    def test_lists_every_file_of_a_directory_git_ignores(self) -> None:
        """A copy in an ignored directory (mutmut's mutants/) is not part of the checkout around it: git tracks none of
        its files, yet they are the project being validated."""
        with temp_project({".gitignore": "copy/\n", "copy/src/main.c": "", "copy/main.o": ""}) as root:
            git(root, "init", "-q")
            git(root, "add", ".gitignore")
            self.assertEqual(Project(root / "copy").tracked_files(), ["main.o", "src/main.c"])

    def test_a_dangling_symlink_is_skipped_not_read(self) -> None:
        """A symlink to nothing (jekyll's test/source/_includes/tmp, argo-cd's testdata/link-to-nowhere) is listed as
        a file and crashes the extraction with FileNotFoundError; it has no content to read and must be skipped."""
        with temp_project({"src/main.c": "int main() {}\n"}) as root:
            try:
                os.symlink("../nowhere", root / "src" / "dangling")
            except OSError as error:  # pragma: no cover - Windows without the privilege
                self.skipTest(f"symlinks cannot be created here: {error}")
            context = make_context(root)
            self.assertIsNone(context.extraction_error)
            self.assertIn("C", context.structure.languages)

    def _read(self, path: str, text: str) -> tuple[Status, bool]:
        """The data-wellformed status of a project of one deeply nested file, and whether its facts say it was nested
        too deeply."""
        with temp_project({path: text}) as root:
            context = make_context(root)
            unknown = any(isinstance(fact, Unknown) and "nested too deeply" in fact.reason for fact in context.facts)
            return data_wellformed.run(context).status, unknown

    def test_deeply_nested_files_do_not_crash_the_extraction(self) -> None:
        job = "jobs:\n  a:\n    runs-on: ubuntu-latest\n"
        cmake = "project(x)\nadd_executable(a a.c)\n"
        generator = "target_compile_options(a PRIVATE " + "$<$<BOOL:1>:" * 500 + "-W" + ">" * 500 + ")\n"
        cases = {
            "CMakeLists.txt": (
                cmake + "if(A)\n" * 3000 + "endif()\n" * 3000,
                cmake + "foreach(i 1)\n" * 3000 + "endforeach()\n" * 3000,
                cmake + "if(" + "(" * 2000 + "A" + ")" * 2000 + ")\nendif()\n",
            ),
            "meson.build": ("x = 'a'" + " + 'a'" * 3000 + "\n",),
            ".github/workflows/ci.yml": (
                job + "    steps:\n      - run: echo\n    x: " + "[" * 3000 + "]" * 3000 + "\n",
                job + "    steps:\n      - run: echo " + "$(" * 2000 + "x" + ")" * 2000 + "\n",
                job + "    if: ${{ " + "(" * 2000 + "true" + ")" * 2000 + " }}\n    steps:\n      - run: echo\n",
            ),
        }
        for path, texts in cases.items():
            for text in texts:
                with self.subTest(path=path, text=text[-30:]):
                    _, unknown = self._read(path, text)
                    if path != ".github/workflows/ci.yml":
                        self.assertTrue(unknown)
        with self.subTest("generator expression"):
            self._read("CMakeLists.txt", cmake + generator)
        with self.subTest("data yaml"):
            status, _ = self._read("data.yaml", "[" * 3000 + "]" * 3000 + "\n")
            self.assertEqual(status, Status.FAIL)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class IgnoredFilesTests(unittest.TestCase):
    """In a git checkout, the files git ignores are not the project's: generated code, a downloaded SDK, mutmut's
    mutants/ copy. Untracked files git does not ignore (new work) are, and so is an ignored file git tracks (#316)."""

    FILES = MappingProxyType(
        {
            ".gitignore": "generated/\n*.log\n",
            "pyproject.toml": "[project]\nname = 'app'\n",
            "src/app.py": "",
            "src/new.py": "",
            "generated/CMakeLists.txt": "project(gen CXX)\n",
            "generated/broken.json": '{"broken":',
            "kept.log": "",
            "debug.log": "",
        }
    )

    def _checkout(self, root: Path) -> None:
        git(root, "init", "-q")
        git(root, "add", ".gitignore", "pyproject.toml", "src/app.py")
        git(root, "add", "-f", "kept.log")

    def test_ignored_files_are_not_listed_but_new_and_tracked_ones_are(self) -> None:
        with temp_project(self.FILES) as root:
            self._checkout(root)
            project = Project(root)
            self.assertEqual(project.files(), [".gitignore", "kept.log", "pyproject.toml", "src/app.py", "src/new.py"])
            self.assertEqual(project.files_in("generated", (".json", ".txt")), [])
            self.assertFalse(project.exists("generated/CMakeLists.txt"))
            self.assertFalse(project.exists("debug.log"))
            self.assertTrue(project.exists("kept.log"))
            self.assertEqual(project.ignored(), ("debug.log", "generated/"))

    def test_an_ignored_directory_adds_no_ecosystem_unit_or_finding(self) -> None:
        with temp_project(self.FILES) as root:
            self._checkout(root)
            context = make_context(root)
            self.assertNotIn("C++", context.structure.languages)
            self.assertNotEqual(data_wellformed.run(context).status, Status.FAIL)

    def test_a_project_in_a_directory_of_a_checkout_asks_the_checkout(self) -> None:
        """A project below the checkout's root (a monorepo member, a corpus fixture) leaves out what git ignores."""
        files = {f"member/{path}": text for path, text in self.FILES.items() if path != ".gitignore"}
        with temp_project({".gitignore": "member/generated/\n", **files}) as root:
            git(root, "init", "-q")
            self.assertNotIn("generated/CMakeLists.txt", Project(root / "member").files())
