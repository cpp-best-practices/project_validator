"""Repository hygiene (upstream #383): what makes the repository's files unsound whatever tools CI runs: Trojan Source
characters, merge-conflict markers, paths that collide by case or that Windows can't check out, broken symbolic
links, and Git LFS pointers committed in place of files. Each fails, but where only a test's data holds it."""

from __future__ import annotations

import os
import unittest
from collections.abc import Mapping
from pathlib import Path

from project_validator.checks.repository_hygiene import repository_hygiene
from project_validator.core import Options, Result, Status
from tests.support import FIXTURES, make_context, temp_project

CONFLICT = "a = 1\n<<<<<<< HEAD\nb = 2\n=======\nb = 3\n>>>>>>> topic\n"
POINTER = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 1234\n"


def _held(root: Path, files: Mapping[str, str]) -> None:
    """Skips the test where the file system can't hold the files' names as given (Windows refuses a colon or a
    trailing dot; macOS and Windows fold case)."""
    held = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if held != set(files):
        raise unittest.SkipTest(f"this file system holds {sorted(held)}, not {sorted(files)}")


def _run(files: Mapping[str, str], links: Mapping[str, str] | None = None, *, limit: int | None = None) -> Result:
    with temp_project(files) as root:
        _held(root, files)
        for link, target in (links or {}).items():
            (root / link).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, root / link)
        options = Options(max_file_size=limit) if limit is not None else None
        return repository_hygiene.run(make_context(root, options))


class RepositoryHygieneTests(unittest.TestCase):
    def test_a_sound_repository_passes(self) -> None:
        self.assertEqual(_run({"src/a.py": "x = 1\n", "docs/title.rst": "Title\n=======\n"}).status, Status.PASS)
        self.assertEqual(repository_hygiene.run(make_context(FIXTURES / "well_configured_cpp")).status, Status.PASS)

    def test_each_defect_fails_and_is_named(self) -> None:
        for files, links, detail in (
            ({"src/a.py": "s = 'abc\u202edef'\n"}, None, "src/a.py:1: a bidirectional control character (U+202E)"),
            ({"src/a.py": CONFLICT}, None, "src/a.py:2: a merge-conflict marker"),
            ({"README.md": "a", "readme.md": "b"}, None, "README.md and readme.md differ only by case"),
            ({"src/aux.h": ""}, None, "src/aux.h: a name Windows reserves"),
            ({"docs/a:b.txt": ""}, None, "docs/a:b.txt: a character Windows does not allow in a name (:)"),
            ({"notes. ": ""}, None, "notes. : a name Windows can't end with a dot or a space"),
            ({"a.txt": ""}, {"link": "missing.txt"}, "link: a symbolic link to missing.txt, which does not exist"),
            ({"assets/logo.png": POINTER}, None, "assets/logo.png: a Git LFS pointer, not the file"),
        ):
            with self.subTest(detail=detail):
                result = _run(files, links)
                self.assertEqual(result.status, Status.FAIL, result)
                self.assertIn(detail, result.details)

    def test_a_checkout_with_windows_line_endings_is_read_alike(self) -> None:
        for path, contents, detail in (
            ("src/a.py", CONFLICT, "src/a.py:2: a merge-conflict marker"),
            ("assets/logo.png", POINTER, "assets/logo.png: a Git LFS pointer, not the file"),
        ):
            with self.subTest(detail=detail), temp_project({}) as root:
                (root / path).parent.mkdir(parents=True)
                (root / path).write_bytes(contents.replace("\n", "\r\n").encode())
                result = repository_hygiene.run(make_context(root))
                self.assertEqual(result.status, Status.FAIL, result)
                self.assertIn(detail, result.details)

    def test_prose_and_data_may_hold_markers_and_right_to_left_text(self) -> None:
        """glib's and pandoc's Arabic translations embed right-to-left text; magit's manual shows a conflict."""
        files = {
            "po/ar.po": 'msgstr "\u202ba\u202c"\n',
            "docs/merging.md": CONFLICT,
            "translations/ar.yaml": 'title: "\u202ba\u202c"\n',
        }
        self.assertEqual(_run(files).status, Status.PASS)

    def test_a_pointer_lfs_stores_is_a_checkout_without_lfs_not_a_defect(self) -> None:
        files = {".gitattributes": "*.png filter=lfs diff=lfs merge=lfs -text\n", "assets/logo.png": POINTER}
        self.assertEqual(_run(files).status, Status.PASS)

    def test_a_tests_data_holding_one_on_purpose_is_reported_not_failed(self) -> None:
        result = _run({"tests/fixtures/conflicted.py": CONFLICT, "src/a.py": "x = 1\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("tests/fixtures/conflicted.py:2: a merge-conflict marker (test code)", result.details)

    def test_binary_and_larger_files_are_not_read_as_text(self) -> None:
        self.assertEqual(_run({"a.bin": "<<<<<<< x\n=======\n>>>>>>> y\n\x00"}).status, Status.PASS)
        self.assertEqual(_run({"big.py": CONFLICT}, limit=len(CONFLICT) - 1).status, Status.PASS)

    def test_gits_own_directory_is_not_looked_in(self) -> None:
        self.assertEqual(_run({"a.txt": ""}, {".git/hooks/pre-commit": "missing"}).status, Status.PASS)

    def test_a_long_list_is_cut_short(self) -> None:
        result = _run({f"src/m{number:02}.py": CONFLICT for number in range(25)})
        self.assertEqual(len(result.details), 22)
        self.assertEqual(result.details[-2], "and 5 more")
