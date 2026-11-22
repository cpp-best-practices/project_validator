"""The shared parsing model: one position type (`Span`) and one error type (`ParseError`) every reader raises."""

from __future__ import annotations

import unittest
from collections.abc import Callable

from project_validator import yaml_support
from project_validator.build_systems.cmake.syntax import CMakeSyntaxError
from project_validator.build_systems.cmake.syntax import parse as parse_cmake
from project_validator.build_systems.meson.syntax import MesonSyntaxError
from project_validator.build_systems.meson.syntax import parse as parse_meson
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError
from project_validator.ecosystems.haskell.cabal import parse as parse_cabal
from project_validator.facts import Origin
from project_validator.facts.settings import unreadable
from project_validator.parsing import ParseError, Span
from project_validator.text import JsonSyntaxError, check_json


class SpanTests(unittest.TestCase):
    def test_a_span_reads_as_line_and_column(self) -> None:
        self.assertEqual(str(Span(3, 7)), "3:7")
        self.assertEqual(str(Span(3)), "3")
        self.assertEqual(str(Span(3, 7, end_line=4, end_column=1)), "3:7")


class ParseErrorTests(unittest.TestCase):
    def test_the_position_is_a_span(self) -> None:
        error = ParseError("bad", 2, 5)
        self.assertEqual((error.message, str(error), error.span), ("bad", "bad", Span(2, 5)))
        self.assertEqual((error.line, error.column), (2, 5))

    def test_a_line_without_a_column_is_a_span_too(self) -> None:
        self.assertEqual(ParseError("bad", 2).span, Span(2))

    def test_no_position_is_no_span(self) -> None:
        error = ParseError("bad")
        self.assertEqual((error.span, error.line, error.column), (None, None, None))

    def test_every_readers_syntax_error_is_a_parse_error_with_its_position(self) -> None:
        cases: dict[type[ParseError], tuple[Callable[[], object], Span | None]] = {
            CMakeSyntaxError: (lambda: parse_cmake("project(x)\nif(a)\n"), Span(2)),
            MesonSyntaxError: (lambda: parse_meson("project('x')\nif true\n"), Span(3)),
            JsonSyntaxError: (lambda: check_json('{"a":\n ]'), Span(2, 2)),
            CabalSyntaxError: (lambda: parse_cabal("name: x\n\tbad: y\n"), Span(2)),
            yaml_support.YamlError: (lambda: yaml_support.load("a: [b\n"), Span(2, 1)),
        }
        for kind, (parse, span) in cases.items():
            with self.subTest(kind=kind.__name__), self.assertRaises(kind) as raised:
                parse()
            self.assertIsInstance(raised.exception, ParseError)
            self.assertIsInstance(raised.exception, ValueError)
            self.assertEqual(raised.exception.span, span)

    def test_messages_are_unchanged(self) -> None:
        with self.assertRaises(CMakeSyntaxError) as raised:
            parse_cmake("project(x)\nif(a)\n")
        self.assertEqual(str(raised.exception), "line 2: if() is never closed with endif()")
        with self.assertRaises(CabalSyntaxError) as cabal:
            parse_cabal("name: x\n\tbad: y\n")
        self.assertEqual(str(cabal.exception), "line 2: tab in indentation")


class OriginSpanTests(unittest.TestCase):
    def test_an_origin_has_no_span_unless_given_one(self) -> None:
        self.assertIsNone(Origin(path="a").span)
        self.assertEqual(Origin(path="a", span=Span(1, 2)).span, Span(1, 2))

    def test_a_span_does_not_change_how_an_origin_reads(self) -> None:
        self.assertEqual(str(Origin(path="a", at=("x",), span=Span(1, 2))), "a:x")

    def test_an_unreadable_file_is_unknown_where_its_error_is(self) -> None:
        self.assertEqual(unreadable("T", "f", ParseError("bad", 4, 2)).origin, Origin(path="f", span=Span(4, 2)))
        self.assertEqual(unreadable("T", "f", ValueError("bad")).origin, Origin(path="f"))
