"""Practices: how requirements are matched in what CI runs."""

import re
import unittest

from project_validator.core import Result
from project_validator.facts import Command, Origin
from project_validator.facts.practices import Practice, Texts, Wording, always, required
from project_validator.policy.practices import judge_any_one
from project_validator.questions import Answer
from project_validator.questions.practices import Compiled, PracticeAnswer
from project_validator.text import pattern


class WordingTests(unittest.TestCase):
    def test_the_policy_words_its_findings_as_the_practice_says(self) -> None:
        """A profile knows what its settings are called and how to set them; a practice the policy's sentences do
        not fit replaces them."""
        standard = required(pattern("-std=f2018", r"-std=f2018"))
        words = Wording(
            kind="Fortran standard settings",
            hint="compile to a standard",
            passed="Fortran is compiled to a standard, with {found}",
            failed="Fortran is never compiled to a standard",
            question="whether Fortran is compiled to a standard",
        )
        practice = Practice(name="x", languages=frozenset({"Fortran"}), requirements=always(standard), words=words)

        def answer(verdict: Answer, found: tuple[tuple[str, tuple[str, ...]], ...]) -> PracticeAnswer:
            compiled = Compiled(compiler=None, found=found, missing=() if found else ("-std=f2018",))
            return PracticeAnswer(language="Fortran", unit=".", practice=practice, answer=verdict, compiled=(compiled,))

        met = answer(Answer.YES, (("-std=f2018", ("CI (ci.yml)",)),))
        self.assertEqual(judge_any_one(met), Result.passed("Fortran is compiled to a standard, with -std=f2018"))
        self.assertEqual(
            judge_any_one(answer(Answer.NO, ())),
            Result.failed("Fortran is never compiled to a standard", "compile to a standard"),
        )
        self.assertIn(
            "whether Fortran is compiled to a standard is unknown", judge_any_one(answer(Answer.UNKNOWN, ())).message
        )


def _command(line: str) -> Command:
    return Command(origin=Origin(path="ci.yml"), job="build", argv=tuple(line.split()), line=line)


class TextsTests(unittest.TestCase):
    def test_hints_narrow_what_is_searched_for_each_requirement(self) -> None:
        """Two requirements may share a pattern but search different commands (`-Werror` for C/C++ and for
        Fortran, found by different hints): each gets its own matches, whichever asks first."""
        cmake, fpm = _command("cmake -DWERROR=ON"), _command("fpm build --flag -DWERROR")
        texts = Texts(found=((cmake, cmake.line), (fpm, fpm.line)))
        pattern = re.compile("WERROR")
        self.assertEqual(texts.matching(pattern, hints=("cmake",)), (cmake,))
        self.assertEqual(texts.matching(pattern, hints=("fpm",)), (fpm,))
        self.assertEqual(texts.matching(pattern), (cmake, fpm))

    def test_patterns_with_the_same_text_but_other_flags_are_matched_apart(self) -> None:
        upper, lower = _command("make WERROR=1"), _command("make werror=1")
        texts = Texts(found=((upper, upper.line), (lower, lower.line)))
        self.assertEqual(texts.matching(re.compile("WERROR")), (upper,))
        self.assertEqual(texts.matching(re.compile("WERROR", re.IGNORECASE)), (upper, lower))
