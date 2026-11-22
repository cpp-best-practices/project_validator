"""The syntax of CMake `if()` arguments: operands to a tree, without consulting any variable."""

from __future__ import annotations

import unittest

from project_validator.build_systems.cmake.condition_syntax import (
    All,
    Any,
    Comparison,
    Not,
    Operand,
    Test,
    Truth,
    parse,
)


def _operands(text: str) -> list[Operand]:
    """Words, a "quoted" one quoted, as `if()` receives them after expansion."""
    return [Operand(word[1:-1], quoted=True) if word.startswith('"') else Operand(word) for word in text.split()]


def _shape(node: object) -> object:
    """A tree as nested tuples, operands by their text (a quoted one in quotes)."""
    if isinstance(node, Operand):
        return f'"{node.text}"' if node.quoted else node.text
    if isinstance(node, Truth):
        return _shape(node.operand)
    if isinstance(node, Test):
        return (node.operator, _shape(node.operand))
    if isinstance(node, Comparison):
        return (_shape(node.left), node.operator, _shape(node.right))
    if isinstance(node, Not):
        return ("NOT", _shape(node.operand))
    if isinstance(node, (All, Any)):
        return ("AND" if isinstance(node, All) else "OR", *(_shape(operand) for operand in node.operands))
    raise TypeError(node)


class TreeTests(unittest.TestCase):
    def test_arguments_parse_by_cmake_precedence(self) -> None:
        for text, tree in (
            ("A", "A"),
            ("EXISTS ${X}", ("EXISTS", "${X}")),
            ("a STREQUAL b", ("a", "STREQUAL", "b")),
            ("NOT NOT A", ("NOT", ("NOT", "A"))),
            # Parentheses, then unary tests, binary tests, NOT, AND, and OR last.
            ("NOT A AND B OR C", ("OR", ("AND", ("NOT", "A"), "B"), "C")),
            ("NOT a STREQUAL b", ("NOT", ("a", "STREQUAL", "b"))),
            ("( A OR B ) AND C", ("AND", ("OR", "A", "B"), "C")),
            ("A AND B AND C", ("AND", "A", "B", "C")),
            ("DEFINED X OR TARGET t", ("OR", ("DEFINED", "X"), ("TARGET", "t"))),
            # A quoted word is never a keyword.
            ('"NOT" STREQUAL x', ('"NOT"', "STREQUAL", "x")),
            ('a "STREQUAL" b', "a"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_shape(parse(_operands(text))), tree)

    def test_no_arguments_is_no_tree(self) -> None:
        self.assertIsNone(parse([]))


class LenientTests(unittest.TestCase):
    """Malformed arguments, which CMake would reject, parse as far as they go, as the evaluator always read them."""

    def test_what_is_missing_is_empty_and_what_follows_is_ignored(self) -> None:
        for text, tree in (
            ("DEFINED", ("DEFINED", "")),
            ("a STREQUAL", ("a", "STREQUAL", "")),
            ("( A", "A"),
            ("A B", "A"),
            ("NOT", ("NOT", "")),
        ):
            with self.subTest(text=text):
                self.assertEqual(_shape(parse(_operands(text))), tree)


if __name__ == "__main__":
    unittest.main()
