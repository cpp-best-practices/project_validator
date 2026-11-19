"""Every check explains why it matters, and `--explain CHECK` prints that with what it looks for and the tools it
recognises for each language."""

from __future__ import annotations

import unittest

from project_validator.cli import EXIT_SUCCESS, EXIT_USAGE
from project_validator.explanations import CATEGORIES, WHY, Explanation, category, explain
from project_validator.plugins import discover
from tests.test_cli import run_cli


class ExplanationTests(unittest.TestCase):
    def test_every_built_in_check_says_why_it_matters(self) -> None:
        self.assertEqual(set(WHY), {found.name for found in discover().checks})

    def test_every_check_is_in_a_known_category(self) -> None:
        for name, reason in WHY.items():
            with self.subTest(check=name):
                self.assertIn(reason.category, CATEGORIES)
                self.assertTrue(reason.why.endswith("."))

    def test_a_plugin_check_without_an_explanation_is_in_other(self) -> None:
        self.assertEqual(category("plugin-check"), "Other")

    def test_an_explanation_names_the_tools_recognised_per_language(self) -> None:
        checks = discover().checks
        found = explain(next(c for c in checks if c.name == "static-analysis"), checks)
        self.assertIn("clang-tidy", found.tools["C++"])
        self.assertIn("clang-tidy", found.tools["C"])
        self.assertEqual(found.level, 2)
        self.assertEqual(found.category, "Analysis")

    def test_an_unscored_check_says_so(self) -> None:
        checks = discover().checks
        lines = explain(next(c for c in checks if c.name == "status-badges"), checks).lines()
        self.assertIn("reported but not scored", "\n".join(lines))
        self.assertIn("Applies to: every project.", lines)

    def test_a_check_without_a_rationale_says_what_it_looks_for_only(self) -> None:
        found = Explanation(
            name="x", description="looks", why="", category="Other", level=4, scored=True, applies_to=(), tools={}
        )
        self.assertEqual(found.lines()[:3], ["x", "", "What it looks for: looks"])
        self.assertNotIn("Why it matters", "\n".join(found.lines()))
        self.assertIn("Category: Other. Needed for Level 4 (Complete).", found.lines())


class ExplainOptionTests(unittest.TestCase):
    def test_explain_prints_what_why_and_the_tools(self) -> None:
        code, output, _ = run_cli("--explain", "fuzz-testing")
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(output.startswith("fuzz-testing\n"))
        self.assertIn("Why it matters: Fuzzers find", output)
        self.assertIn("Tools recognised:", output)
        self.assertIn("  Rust: cargo-fuzz", output)

    def test_an_old_name_is_explained_too(self) -> None:
        self.assertTrue(run_cli("--explain", "cxx-extensions")[1].startswith("compiler-extensions\n"))

    def test_an_unknown_check_is_a_usage_error(self) -> None:
        code, _, errors = run_cli("--explain", "nonsense")
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("unknown check(s): nonsense", errors)


if __name__ == "__main__":
    unittest.main()
