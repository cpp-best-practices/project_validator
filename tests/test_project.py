import unittest

from project_validator.core import Project
from tests.support import temp_project


class ProjectTests(unittest.TestCase):
    def test_finds_cmake_files_recursively(self) -> None:
        files = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "cmake/Warnings.cmake": "", "src/main.cpp": ""}
        with temp_project(files) as root:
            self.assertEqual(
                Project(root).cmake_files(), ["CMakeLists.txt", "cmake/Warnings.cmake", "src/CMakeLists.txt"]
            )

    def test_skips_hidden_directories_and_build_trees(self) -> None:
        files = {
            "CMakeLists.txt": "",
            ".git/CMakeLists.txt": "",
            "out/CMakeCache.txt": "",
            "out/_deps/x/CMakeLists.txt": "",
        }
        with temp_project(files) as root:
            self.assertEqual(Project(root).cmake_files(), ["CMakeLists.txt"])

    def test_files_in_filters_by_suffix_and_ignores_missing_directories(self) -> None:
        files = {"w/a.yml": "", "w/b.yaml": "", "w/c.txt": ""}
        with temp_project(files) as root:
            project = Project(root)
            self.assertEqual(project.files_in("w", (".yml", ".yaml")), ["w/a.yml", "w/b.yaml"])
            self.assertEqual(project.files_in("missing", (".yml",)), [])
