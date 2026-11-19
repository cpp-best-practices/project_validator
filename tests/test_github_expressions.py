"""GitHub Actions expressions, evaluated as far as a checkout shows their values."""

from __future__ import annotations

import unittest

from project_validator.ci.github_expressions import Known, evaluate, rendered

KNOWN = Known(
    os="linux",
    matrix={"compiler": "gcc-14", "config": {"os": "windows-latest"}, "shared": True, "generator": None},
    env={"CLANG_TIDY_VERSION": "19.1.1"},
)


class EvaluateTests(unittest.TestCase):
    def test_what_the_checkout_shows(self) -> None:
        for condition, expected in (
            ("runner.os != 'Windows'", True),
            ("${{ runner.os == 'windows' }}", False),  # comparisons ignore case
            ("matrix.generator != ''", False),  # null is empty
            ("matrix.config.os == 'windows-latest'", True),
            ("matrix.shared", True),
            ("matrix.compiler.version == ''", True),  # a property of a string is null
            ("!matrix.shared", False),
            ("contains(matrix.compiler, 'llvm') && !contains(matrix.compiler, env.CLANG_TIDY_VERSION)", False),
            ("startsWith(matrix.compiler, 'GCC') || endsWith(matrix.compiler, '13')", True),
            ("(runner.os == 'Linux') && 1 == 1.0", True),
            ("'it''s' == 'IT''S'", True),
            ("true && null", False),
            ("success()", True),
            ("always()", True),
            ("failure()", False),
            ("cancelled()", False),
        ):
            with self.subTest(condition=condition):
                self.assertEqual(evaluate(condition, KNOWN), expected)

    def test_what_it_does_not_show_decides_nothing_unless_the_rest_does(self) -> None:
        for condition, expected in (
            ("github.event_name == 'push'", None),
            ("!github.event.pull_request", None),
            ("github.event_name == 'push' && runner.os == 'Windows'", False),
            ("github.event_name == 'push' || runner.os == 'Linux'", True),
            ("github.event_name == 'push' || runner.os == 'Windows'", None),
            ("steps.build.outcome == 'success' && runner.os == 'Linux'", None),
            ("contains(fromJSON('[1]'), 1)", None),
            ("contains(github.ref, 'tags')", None),
            ("hashFiles('**/x')", None),
            ("runner.os == ", None),
            ("runner.os == 'Linux' 'extra'", None),
            ("runner.os == $", None),
            ("", None),
        ):
            with self.subTest(condition=condition):
                self.assertEqual(evaluate(condition, KNOWN), expected)

    def test_an_unknown_runner_os_is_unknown(self) -> None:
        self.assertIsNone(evaluate("runner.os == 'Linux'", Known(os="unknown", matrix={}, env={})))

    def test_a_matrix_computed_by_an_expression_is_unknown(self) -> None:
        """A matrix that is not expanded (`${{ fromJSON(...) }}`) has values, just not seen: a condition on one is
        not false, it is unknown, so the step is not dropped."""
        known = Known(os="linux", matrix={}, env={}, matrix_known=False)
        self.assertIsNone(evaluate("matrix.coverage == 'true'", known))
        self.assertIsNone(evaluate("matrix.lint", known))
        self.assertTrue(evaluate("runner.os == 'Linux'", known))


class DepthTests(unittest.TestCase):
    def test_deep_nesting_is_unknown(self) -> None:
        self.assertIsNone(evaluate("(" * 5000 + "true" + ")" * 5000, KNOWN))
        self.assertIsNone(rendered("${{ " + "(" * 5000 + "'a'" + ")" * 5000 + " }}", KNOWN))


class RenderedTests(unittest.TestCase):
    def test_values_are_rendered_as_github_renders_them(self) -> None:
        for expression, expected in (
            ("${{ runner.os }}", "Linux"),
            ("${{ matrix.compiler == 'gcc-14' }}", "true"),
            ("${{ matrix.generator }}", ""),
            ("${{ 3 }}", "3"),
            ("${{ 1.5 }}", "1.5"),
            ("${{ github.sha }}", None),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(rendered(expression, KNOWN), expected)


class UndecidedOperandTests(unittest.TestCase):
    """When the left operand of `||` or `&&` is not known, the right one may still decide a condition, but never the
    value: `${{ inputs.flags || '-DX=1' }}` renders either operand, so it is not known (#214)."""

    def test_an_unknown_left_operand_decides_a_condition_but_not_a_value(self) -> None:
        for expression, condition in (
            ("github.event.inputs.flags || '-DX=1'", True),
            ("github.event.inputs.flags && ''", False),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(evaluate(expression, KNOWN), condition)
                self.assertIsNone(rendered(f"${{{{ {expression} }}}}", KNOWN))

    def test_an_undecided_value_compares_and_calls_as_unknown(self) -> None:
        for expression in (
            "(github.event.inputs.flags || 'x') == 'x'",
            "contains(github.event.inputs.flags || 'x', 'x')",
        ):
            with self.subTest(expression=expression):
                self.assertIsNone(evaluate(expression, KNOWN))

    def test_a_known_operand_still_renders_its_value(self) -> None:
        self.assertEqual(rendered("${{ matrix.generator || 'Ninja' }}", KNOWN), "Ninja")
        self.assertEqual(rendered("${{ (github.event.inputs.flags || 'x') && 'y' }}", KNOWN), "y")
