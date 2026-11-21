"""The wording every message and view shares: counted nouns, and folders named the same way everywhere."""

from __future__ import annotations

import unittest

from project_validator.words import counted, folder


class CountedTests(unittest.TestCase):
    def test_one_is_singular_and_every_other_count_plural(self) -> None:
        self.assertEqual([counted(n, "file") for n in (0, 1, 2)], ["0 files", "1 file", "2 files"])

    def test_an_irregular_plural_is_given(self) -> None:
        self.assertEqual(counted(3, "directory", "directories"), "3 directories")


class FolderTests(unittest.TestCase):
    def test_the_root_is_named_and_a_folder_ends_in_a_slash(self) -> None:
        self.assertEqual((folder("."), folder("src/app")), ("the root", "src/app/"))

    def test_a_unit_is_named_without_the_slash(self) -> None:
        self.assertEqual((folder(".", slash=False), folder("tools", slash=False)), ("the root", "tools"))


if __name__ == "__main__":
    unittest.main()
