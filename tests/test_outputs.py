"""The build output model: which outputs a language's project has, by the build systems it uses."""

from __future__ import annotations

import re
import unittest

from project_validator.facts.outputs import BuildOutput, _glob_ignores, outputs_of


def _output(name: str, *build_systems: str, language: str = "L") -> BuildOutput:
    return BuildOutput(
        languages=frozenset({language}),
        name=name,
        globs=re.compile(name),
        paths=(name,),
        hint="",
        build_systems=frozenset(build_systems),
    )


class OutputsOfTests(unittest.TestCase):
    def test_a_build_systems_outputs_add_to_the_languages_own(self) -> None:
        own, maven, gradle = _output("own"), _output("maven", "Maven"), _output("gradle", "Gradle")
        other = _output("x", language="M")
        outputs = (own, maven, gradle, other)
        self.assertEqual(outputs_of("L", frozenset({"Maven"}), outputs), (own, maven))
        self.assertEqual(outputs_of("L", frozenset(), outputs), (own,))
        self.assertEqual(outputs_of("L", frozenset({"Maven", "Gradle"}), outputs), (own, maven, gradle))
        self.assertEqual(outputs_of("M", frozenset({"Maven"}), outputs), (other,))


class GlobIgnoresTests(unittest.TestCase):
    def test_globs_match_as_gitignore_entries(self) -> None:
        cases = {
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
        }
        for (glob, path), ignored in cases.items():
            with self.subTest(glob=glob, path=path):
                self.assertIs(_glob_ignores(glob, path), ignored)
