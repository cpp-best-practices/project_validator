import unittest
from pathlib import PurePosixPath

from project_validator.core import Project
from tests.support import PROJECT_LAYOUTS, layout_project, temp_project


class ProjectTests(unittest.TestCase):
    def test_finds_cmake_files_recursively(self) -> None:
        files = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "cmake/Warnings.cmake": "", "src/main.cpp": ""}
        with temp_project(files) as root:
            self.assertEqual(
                Project(root).cmake_files(), ["CMakeLists.txt", "cmake/Warnings.cmake", "src/CMakeLists.txt"]
            )

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
