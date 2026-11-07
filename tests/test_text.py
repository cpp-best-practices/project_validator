import unittest

from project_validator.text import matching_names, pattern


class MatchingNamesTests(unittest.TestCase):
    def test_reports_each_name_once_in_pattern_order(self) -> None:
        patterns = (pattern("b", "bee"), pattern("a", "ay"), pattern("b", "buzz"))
        self.assertEqual(matching_names(["ay bee", "buzz"], patterns), ["b", "a"])

    def test_is_case_insensitive(self) -> None:
        self.assertEqual(matching_names(["CLANG"], (pattern("clang", "clang"),)), ["clang"])
