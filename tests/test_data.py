"""The Data profile: a format ecosystem, with a parser for each of its formats."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from project_validator.ecosystems import data
from project_validator.ecosystems.data import DATA
from project_validator.facts.structure import NOT_SOURCE_SUFFIXES
from project_validator.facts.wellformed import ParseError, known_parsers
from project_validator.limits import JSON_NESTING
from project_validator.text import check_json
from tests.support import make_context, temp_project


class DataFormatTests(unittest.TestCase):
    def test_data_is_a_format_ecosystem_with_a_parser_for_each_format(self) -> None:
        self.assertEqual((DATA.kind, DATA.toolchain, DATA.build_systems), ("format", None, ()))
        parsers = {parser.format for parser in known_parsers() if parser.format in DATA.languages}
        self.assertEqual(parsers, DATA.languages)

    def test_data_files_are_the_projects_formats_and_are_never_unrecognised(self) -> None:
        files = {"a.json": "{}", "b.toml": "", "c.yml": "", "d.xml": "<a/>", "e.xsd": "<a/>", "f.jsonc": "{}"}
        with temp_project(files) as root:
            structure = make_context(root).structure
        # The XSD makes it an XML Schema project too; the Data formats are all there.
        self.assertEqual((structure.languages, structure.formats & DATA.languages), (frozenset(), DATA.languages))
        signals = (".json files", ".jsonc files", ".toml files", ".xml files", ".xsd files", ".yml files")
        self.assertEqual(structure.recognised_by["Data"], signals)
        self.assertEqual(structure.unrecognised_suffixes, ())
        self.assertFalse(set(DATA.source_suffixes or {}) & NOT_SOURCE_SUFFIXES)


class ParserTests(unittest.TestCase):
    def test_json_comments_are_allowed_where_tools_read_them(self) -> None:
        jsonc = b'{\n  // the compiler\n  "url": "http://example.com/*x*/", /* block */\n  "list": [1, 2,],\n}\n'
        for path in ("tsconfig.json", "web/tsconfig.base.json", ".vscode/settings.json", "a.jsonc", "jsconfig.json"):
            with self.subTest(path=path):
                data.JSON_PARSER.parse(path, jsonc)
        with self.assertRaises(ParseError) as raised:
            data.JSON_PARSER.parse("package.json", jsonc)
        self.assertEqual((raised.exception.line, raised.exception.column), (2, 3))

    def test_the_reader_without_recursion_agrees_with_json(self) -> None:
        good = ("1", "[]", "{}", '{"a":[1,2,{"b":null}]}', ' "x" ', '{"a":{"b":[true,false]},"c":"\\u0041"}')
        bad: tuple[str, ...] = (
            "[1,]",
            '{"a"}',
            "{1:2}",
            "[1 2]",
            "[",
            '{"a":1,}',
            "[]]",
            "[}",
            '{"a":1 "b":2}',
            "",
            "{[1]:2}",
        )
        bad = (*bad, "1 2", ":", ",", '{"a":}', "]", '{"a",1}', "[1:2]")
        for text in good:
            with self.subTest(text=text):
                check_json(text)
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ParseError):
                check_json(text)

    def test_json_counts_as_deep_only_past_the_limit(self) -> None:
        limit = JSON_NESTING.most
        cases = {
            "[" * limit + "]" * limit: False,
            "[" * (limit + 1) + "]" * (limit + 1): True,
            "{" * (limit + 1): True,
            # Closed containers do not add up, and brackets inside strings are not containers.
            "[[]]" * (limit + 1): False,
            "{}" * (limit + 1): False,
            '"' + "[" * (limit + 1) + '"': False,
            "[" * limit + '"]"' + "[": True,
        }
        for text, deep in cases.items():
            with self.subTest(text=text[:20], length=len(text)):
                self.assertIs(data._deep(text), deep)

    def test_deeply_nested_json_is_reported_the_same_whatever_python_recurses(self) -> None:
        """JSONTestSuite's `n_structure_100000_opening_arrays.json` (denoland/std, yojson) is reported the same on a
        Python whose decoder raises RecursionError and on one that reads that deep and fails on the end."""
        text = b"[" * 100000
        reported = []
        for raised in (RecursionError(), json.JSONDecodeError("Expecting value", "[" * 100000, 100000)):
            with mock.patch("json.loads", side_effect=raised), self.assertRaises(ParseError) as caught:
                data._parse_json("deep.json", text)
            reported.append((str(caught.exception), caught.exception.line, caught.exception.column))
        self.assertEqual(reported[0], reported[1])
