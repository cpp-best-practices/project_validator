"""The build output model: which outputs a language's project has, by the build systems it uses."""

from __future__ import annotations

import re
import unittest

from project_validator.facts.outputs import BuildOutput, outputs_of


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
