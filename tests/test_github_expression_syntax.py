"""The syntax of GitHub Actions expressions: text to a tree with spans, without consulting what a checkout shows."""

from __future__ import annotations

import unittest

from project_validator.ci.github_expression_syntax import (
    Call,
    Comparison,
    ExpressionSyntaxError,
    Index,
    Literal,
    Logical,
    Not,
    Reference,
    parse,
)
from project_validator.limits import GITHUB_EXPRESSION_NESTING
from project_validator.parsing import ParseError, Span


def _shape(node: object) -> object:
    """A node without its spans, for comparing trees."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Reference):
        return ("ref", node.name)
    if isinstance(node, Not):
        return ("!", _shape(node.operand))
    if isinstance(node, Comparison):
        return (node.operator, _shape(node.left), _shape(node.right))
    if isinstance(node, Logical):
        return (node.operator, *(_shape(operand) for operand in node.operands))
    if isinstance(node, Call):
        return ("call", node.name, *(_shape(argument) for argument in node.arguments))
    if not isinstance(node, Index):
        raise TypeError(node)
    return ("[]", _shape(node.target), _shape(node.key))


class TreeTests(unittest.TestCase):
    def test_expressions_parse_to_trees(self) -> None:
        for text, tree in (
            ("true", True),
            ("null", None),
            ("'it''s'", "it's"),
            ("-1.5", -1.5),
            ("matrix.config.os", ("ref", "matrix.config.os")),
            ("${{ runner.os }}", ("ref", "runner.os")),
            ("!a", ("!", ("ref", "a"))),
            ("!!a", ("!", ("!", ("ref", "a")))),
            ("a == 'x'", ("==", ("ref", "a"), "x")),
            ("a < 1", ("<", ("ref", "a"), 1.0)),
            # `!` binds tighter than ordering, which binds tighter than equality, then `&&`, then `||`.
            ("!a < b == c", ("==", ("<", ("!", ("ref", "a")), ("ref", "b")), ("ref", "c"))),
            ("a || b && c", ("||", ("ref", "a"), ("&&", ("ref", "b"), ("ref", "c")))),
            # A chain of one operator is one node, as GitHub's runner builds it.
            ("a && b && c", ("&&", ("ref", "a"), ("ref", "b"), ("ref", "c"))),
            ("(a || b) && c", ("&&", ("||", ("ref", "a"), ("ref", "b")), ("ref", "c"))),
            ("contains(a, 'x')", ("call", "contains", ("ref", "a"), "x")),
            ("success()", ("call", "success")),
            ("github.event['pull_request']", ("[]", ("ref", "github.event"), "pull_request")),
        ):
            with self.subTest(text=text):
                self.assertEqual(_shape(parse(text)), tree)

    def test_nodes_say_where_they_are(self) -> None:
        tree = parse("a ==\n  'b'")
        if not isinstance(tree, Comparison):
            self.fail(f"not a comparison: {tree}")
        self.assertEqual(tree.left.span, Span(1, 1, 1, 2))
        self.assertEqual(tree.right.span, Span(2, 3, 2, 6))
        self.assertEqual(tree.span, Span(1, 1, 2, 6))

    def test_spans_count_from_inside_the_braces(self) -> None:
        self.assertEqual(parse("${{ a }}").span, Span(1, 5, 1, 6))


class SyntaxErrorTests(unittest.TestCase):
    def test_what_does_not_parse_says_where(self) -> None:
        for text, column in (
            ("", None),
            ("runner.os == ", None),
            ("runner.os == 'Linux' 'extra'", 22),
            ("runner.os == $", 14),
            ("(a", None),
            ("(a b)", 4),
            ("contains(a 'x')", 12),
            ("f(a,)", 5),
            ("'unclosed", 1),
        ):
            with self.subTest(text=text), self.assertRaises(ExpressionSyntaxError) as raised:
                parse(text)
            self.assertIsInstance(raised.exception, ParseError)
            self.assertEqual(raised.exception.column, column)


class NestingTests(unittest.TestCase):
    """GitHub's runner rejects a tree more than 50 levels deep; so does the parser, before Python's stack would."""

    def test_trees_nest_at_most_the_limit_deep(self) -> None:
        most = GITHUB_EXPRESSION_NESTING.most
        parse("!" * (most - 1) + "a")
        with self.assertRaises(ExpressionSyntaxError) as raised:
            parse("!" * most + "a")
        self.assertIn(GITHUB_EXPRESSION_NESTING.reason, raised.exception.message)

    def test_parentheses_add_no_level_but_cannot_exhaust_the_stack(self) -> None:
        parse("(" * 10 + "a" + ")" * 10)
        with self.assertRaises(ExpressionSyntaxError):
            parse("(" * 5000 + "a" + ")" * 5000)

    def test_a_long_chain_of_one_operator_is_one_level(self) -> None:
        parse(" || ".join(["a"] * 5000))


if __name__ == "__main__":
    unittest.main()
