"""Practices: how requirements are matched in what CI runs."""

import re
import unittest

from project_validator.facts import Command, Origin
from project_validator.facts.practices import Texts


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
