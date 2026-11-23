"""The syntax of CMake generator expressions: text to literal parts and expressions, without evaluating any."""

from __future__ import annotations

import unittest

from project_validator.build_systems.cmake.generator_syntax import Expression, Template, parse, split, written


def _shape(template: Template) -> list[object]:
    """A template as nested lists: text as itself, an expression as (name, rest), rest None without a colon."""
    return [
        part if isinstance(part, str) else (_shape(part.name), None if part.rest is None else _shape(part.rest))
        for part in template
    ]


class ParseTests(unittest.TestCase):
    def test_text_and_expressions_with_their_name_and_rest(self) -> None:
        self.assertEqual(
            _shape(parse("-W$<$<CONFIG:Debug>:all,extra>x")),
            ["-W", ([(["CONFIG"], ["Debug"])], ["all,extra"]), "x"],
        )

    def test_an_expression_without_a_colon_has_no_rest(self) -> None:
        self.assertEqual(_shape(parse("a$<SEMICOLON>b")), ["a", (["SEMICOLON"], None), "b"])

    def test_the_name_ends_at_the_first_colon_outside_nested_expressions(self) -> None:
        [expression] = parse("$<$<STREQUAL:a,b>:x:y>")
        self.assertIsInstance(expression, Expression)
        self.assertEqual(_shape(parse("$<$<STREQUAL:a,b>:x:y>")), [([(["STREQUAL"], ["a,b"])], ["x:y"])])

    def test_an_expression_never_closed_is_text_to_the_end(self) -> None:
        """What it would hold is text too: the `>` that closes `$<c>` leaves `$<b` open."""
        self.assertEqual(_shape(parse("a$<b$<c>")), ["a$<b$<c>"])
        self.assertEqual(_shape(parse("$<unclosed")), ["$<unclosed"])

    def test_each_expression_keeps_where_and_how_it_is_written(self) -> None:
        [text, expression] = parse("-W$<IF:$<BOOL:x>,a,b>")
        self.assertEqual(text, "-W")
        self.assertIsInstance(expression, Expression)
        if isinstance(expression, Expression):
            self.assertEqual((expression.written, expression.start, expression.end), ("$<IF:$<BOOL:x>,a,b>", 2, 21))
        self.assertEqual(written(parse("x$<A:$<B>,c>y")), "x$<A:$<B>,c>y")


class SplitTests(unittest.TestCase):
    def test_a_template_splits_at_separators_outside_nested_expressions(self) -> None:
        [expression] = parse("$<IF:$<AND:a,b>,x,y>")
        rest = expression.rest if isinstance(expression, Expression) else None
        self.assertEqual([written(part) for part in split(rest or (), ",")], ["$<AND:a,b>", "x", "y"])
        self.assertEqual(split((), ","), [()])


if __name__ == "__main__":
    unittest.main()
