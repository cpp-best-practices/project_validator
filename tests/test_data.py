"""The Data profile: a format ecosystem, with a parser for each of its formats."""

from __future__ import annotations

import unittest

from project_validator.ecosystems import data
from project_validator.ecosystems.data import DATA
from project_validator.facts.structure import NOT_SOURCE_SUFFIXES
from project_validator.facts.wellformed import ParseError, known_parsers
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
        self.assertEqual((structure.languages, structure.formats), (frozenset(), DATA.languages))
        signals = (".json files", ".jsonc files", ".toml files", ".xml files", ".xsd files", ".yml files")
        self.assertEqual(structure.recognised_by, {"Data": signals})
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
                data._check_deep_json(text)
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ParseError):
                data._check_deep_json(text)
