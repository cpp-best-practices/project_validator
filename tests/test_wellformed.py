"""The data files' facts: each of the project's files in a format with a parser, parsed once at extraction."""

from __future__ import annotations

import types
import unittest
from collections.abc import Mapping
from unittest import mock

from project_validator.components import add_plugin_modules
from project_validator.core import Project
from project_validator.ecosystems import isolated_registry, register
from project_validator.facts import Origin
from project_validator.facts.wellformed import DataFile, ParseError, Parser, data_file_facts, parsed_formats
from tests.support import FORMAT_ECOSYSTEM, make_context, temp_project


def _parse(_path: str, data: bytes) -> None:
    if data == b"bad":
        raise ParseError("bad data", 2, 3)
    if data == b"where?":
        raise ParseError("somewhere")
    if data == b"deep":
        raise RecursionError


PARSER = Parser(format="WDATA", parse=_parse)


def _data_files(files: Mapping[str, str]) -> dict[str, DataFile]:
    with isolated_registry(), temp_project(files) as root:
        register(FORMAT_ECOSYSTEM)
        context = make_context(root)
        return {found.path: found for found in data_file_facts(context.project, context.facts, (PARSER,))}


class DataFileTests(unittest.TestCase):
    def test_each_of_the_projects_own_files_in_a_format_with_a_parser_is_parsed(self) -> None:
        files = {"a.wdata": "good", "b.wdata": "bad", "tests/c.wdata": "bad", "vendor/d.wdata": "bad", "e.wdg": "bad"}
        found = _data_files(files)
        self.assertEqual(set(found), {"a.wdata", "b.wdata", "tests/c.wdata"})
        self.assertEqual(found["a.wdata"], DataFile(origin=Origin(path="a.wdata"), format="WDATA"))
        self.assertEqual(
            found["b.wdata"],
            DataFile(origin=Origin(path="b.wdata"), format="WDATA", problem="bad data", line=2, column=3),
        )
        self.assertEqual((found["tests/c.wdata"].role, found["tests/c.wdata"].problem), ("test", "bad data"))

    def test_a_problem_may_have_no_position_and_a_file_may_be_nested_too_deeply(self) -> None:
        found = _data_files({"a.wdata": "where?", "b.wdata": "deep"})
        self.assertEqual(
            (found["a.wdata"].problem, found["a.wdata"].line, found["a.wdata"].column), ("somewhere", None, None)
        )
        self.assertEqual(found["b.wdata"].problem, "nested too deeply to read")

    def test_a_file_too_large_to_parse_is_recorded_as_unread(self) -> None:
        with mock.patch.object(Project, "size", return_value=5 * 1024 * 1024 + 1):
            [found] = _data_files({"a.wdata": "bad"}).values()
        self.assertEqual((found.problem, found.unread), (None, "larger than 5 MiB"))

    def test_the_data_files_are_facts_parsed_by_the_known_parsers(self) -> None:
        plugin = types.ModuleType("wdata_plugin")
        plugin.PARSER = PARSER  # type: ignore[attr-defined]
        with isolated_registry(), temp_project({"a.wdata": "bad"}) as root:
            register(FORMAT_ECOSYSTEM)
            add_plugin_modules([plugin])
            self.assertIn("WDATA", parsed_formats())
            [found] = make_context(root).facts.of(DataFile)
        self.assertEqual((found.path, found.problem), ("a.wdata", "bad data"))
        self.assertNotIn("WDATA", parsed_formats())
