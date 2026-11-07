import unittest

from project_validator.text import found_and_missing, matching_names, pattern


class MatchingNamesTests(unittest.TestCase):
    def test_reports_each_name_once_in_pattern_order(self) -> None:
        patterns = (pattern("b", "bee"), pattern("a", "ay"), pattern("b", "buzz"))
        self.assertEqual(matching_names(["ay bee", "buzz"], patterns), ["b", "a"])

    def test_is_case_insensitive(self) -> None:
        self.assertEqual(matching_names(["CLANG"], (pattern("clang", "clang"),)), ["clang"])


class FoundAndMissingTests(unittest.TestCase):
    def test_splits_names_by_whether_any_text_matches_in_pattern_order(self) -> None:
        patterns = (pattern("c", "sea"), pattern("a", "ay"), pattern("b", "bee"))
        self.assertEqual(found_and_missing(["ay", "SEA"], patterns), (["c", "a"], ["b"]))

    def test_everything_is_missing_without_texts(self) -> None:
        self.assertEqual(found_and_missing([], (pattern("a", "ay"),)), ([], ["a"]))
