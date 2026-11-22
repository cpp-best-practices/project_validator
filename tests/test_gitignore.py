"""Gitignore matching: git's answers, and a missing pathspec reported instead of crashing."""

from __future__ import annotations

import unittest
from unittest import mock

from project_validator import gitignore

# (glob, path): whether the glob, as a gitignore entry at the top, ignores the path (a directory when it ends
# in "/").
_CASES = {
    # A glob without a slash matches a name at any depth; a directory it matches holds what is below it.
    ("build", "build"): True,
    ("build", "src/build/a.o"): True,
    ("build", "src/builder"): False,
    ("*.o", "src/a.o"): True,
    ("?.o", "src/ab.o"): False,
    ("ab*", "abc"): True,
    ("ab*", "xabc"): False,
    ("[ab].o", "b.o"): True,
    ("[ab].o", "c.o"): False,
    # A trailing slash matches directories only: a file of that name is not ignored.
    ("build/", "src/build"): False,
    ("build/", "src/build/"): True,
    ("build/", "build/a.o"): True,
    # A slash anchors the glob at the top; `**` spans directories.
    ("/build", "src/build"): False,
    ("/build", "build/a.o"): True,
    ("src/*.o", "src/a.o"): True,
    ("src/*.o", "lib/src/a.o"): False,
    ("**/gen", "a/b/gen/x"): True,
    ("**/gen", "a/bgen"): False,
    ("a/**/b", "a/x/y/b"): True,
    # git's answers (`git check-ignore --no-index`), including its wildmatch cases: `**/` and `/**/` match
    # zero directories too, `*` and `?` never match a slash, and a glob with an inner slash is anchored.
    ("**/gen", "gen/x"): True,
    ("**/gen", "gen"): True,
    ("docs/**/*.html", "docs/x.html"): True,
    ("docs/**/*.html", "docs/a/b/x.html"): True,
    ("foo/**/bar", "foo/bar"): True,
    ("abc/**", "abc/x"): True,
    ("[!a].o", "b.o"): True,
    ("[!a].o", "a.o"): False,
    ("[a-c].o", "b.o"): True,
    ("[a-c].o", "d.o"): False,
    ("\\#foo", "#foo"): True,
    ("a?c", "a/c"): False,
    ("a*c", "a/c"): False,
    ("src/", "x/src/"): True,
    ("/src/", "x/src/"): False,
    ("a/b", "x/a/b"): False,
    ("*", "anything/at/all"): True,
}


class GlobIgnoresTests(unittest.TestCase):
    def test_globs_match_as_gitignore_entries(self) -> None:
        for (glob, path), ignored in _CASES.items():
            with self.subTest(glob=glob, path=path):
                self.assertIs(gitignore.ignores(glob, path), ignored)


class MissingPathspecTests(unittest.TestCase):
    def test_a_missing_install_is_detected(self) -> None:
        with mock.patch("importlib.import_module", side_effect=ImportError):
            self.assertIsNone(gitignore._import_pathspec())

    def test_matching_without_pathspec_explains_how_to_install_it(self) -> None:
        gitignore._spec.cache_clear()
        with mock.patch.object(gitignore, "_pathspec", None), self.assertRaises(RuntimeError) as raised:
            gitignore.ignores("build/", "build/")
        self.assertEqual(str(raised.exception), gitignore.MISSING_MESSAGE)
