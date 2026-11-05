import unittest
from collections.abc import Mapping
from pathlib import PurePosixPath
from unittest import mock

from project_validator.checks import data_wellformed as module
from project_validator.checks.data_wellformed import data_wellformed
from project_validator.core import Options, Project, Result, Status
from tests.support import FIXTURES, make_context, temp_project


def _run(files: Mapping[str, str], binary: Mapping[str, bytes] | None = None, *, exclude: str = "") -> Result:
    with temp_project(files) as root:
        for path, data in (binary or {}).items():
            (root / path).write_bytes(data)
        context = make_context(root)
        if exclude:
            context.project = Project(root, frozenset({PurePosixPath(exclude)}))
        return data_wellformed.run(context)


class DataWellformedTests(unittest.TestCase):
    def assert_fails(self, files: Mapping[str, str], *problems: str, binary: Mapping[str, bytes] | None = None) -> None:
        result = _run(files, binary)
        self.assertEqual(result.status, Status.FAIL, result.message)
        self.assertEqual(result.details, problems)

    def test_applies_to_every_language(self) -> None:
        self.assertEqual(data_wellformed.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = data_wellformed.run(make_context(FIXTURES / "well_configured", Options()))
        self.assertEqual(result.status, Status.PASS)
        self.assertRegex(result.message, r"^\d+ data files parse \(.*YAML: \d+\)$")

    def test_passes_without_data_files(self) -> None:
        result = _run({"src/main.cpp": ""})
        self.assertEqual(result, Result.passed("no JSON, TOML, YAML or XML files to parse"))

    def test_counts_the_files_of_each_format(self) -> None:
        files = {"a.json": "{}", "b.toml": "x = 1", "c.yml": "a: 1", "d.yaml": "", "e.xml": "<a/>", "f.xsd": "<s/>"}
        self.assertEqual(_run(files).message, "6 data files parse (JSON: 1, TOML: 1, XML: 2, YAML: 2)")
        self.assertEqual(_run({"a.json": "[]"}).message, "1 data file parses (JSON: 1)")

    def test_reports_where_each_file_does_not_parse(self) -> None:
        self.assert_fails(
            {"package.json": '{\n  "name": "app",\n}\n', "Cargo.toml": "[package\n"},
            "Cargo.toml:1:9: Expected ']' at the end of a table declaration",
            "package.json:2:16: Illegal trailing comma before end of object",
        )
        self.assertEqual(_run({"a.json": "{", "b.json": "{}"}).message, "1 data file does not parse")

    def test_every_yaml_document_must_parse(self) -> None:
        self.assert_fails(
            {"docs.yaml": "a: 1\n---\nb: [2\n"}, "docs.yaml:4:1: expected ',' or ']', but got '<stream end>'"
        )

    def test_yaml_tags_of_any_tool_are_accepted(self) -> None:
        files = {".gitlab-ci.yml": "test:\n  script: !reference [.setup, script]\n", "stack.yaml": "Value: !Ref Name\n"}
        self.assertEqual(_run(files).status, Status.PASS)

    def test_yaml_with_control_characters_does_not_parse(self) -> None:
        result = _run({"a.yml": "a: \x07\n"})
        self.assertEqual(result.status, Status.FAIL)
        self.assertRegex(result.details[0], r"^a\.yml: unacceptable character")

    def test_xml_must_be_well_formed(self) -> None:
        self.assert_fails({"pom.xml": "<project>\n  <name>app</project>\n"}, "pom.xml:2:14: mismatched tag")

    def test_xml_external_entities_are_never_read(self) -> None:
        document = (
            '<?xml version="1.0"?>\n<!DOCTYPE a SYSTEM "missing.dtd" [<!ENTITY e SYSTEM "missing.txt">]>\n<a>&e;</a>\n'
        )
        self.assertEqual(_run({"a.xml": document}).status, Status.PASS)

    def test_json_with_comments_is_allowed_where_tools_allow_it(self) -> None:
        jsonc = '{\n  // the compiler\n  "url": "http://example.com/*x*/", /* block */\n  "list": [1, 2,],\n}\n'
        files = {
            "tsconfig.json": jsonc,
            "web/tsconfig.base.json": jsonc,
            ".vscode/settings.json": jsonc,
            "a.jsonc": jsonc,
        }
        self.assertEqual(_run(files).message, "4 data files parse (JSON: 4)")
        self.assert_fails(
            {"package.json": jsonc}, "package.json:2:3: Expecting property name enclosed in double quotes"
        )

    def test_comments_keep_the_positions_of_later_problems(self) -> None:
        self.assert_fails(
            {"a.jsonc": '{\n  /* one\n  two */ "a": 1\n  "b": 2\n}\n'}, "a.jsonc:4:3: Expecting ',' delimiter"
        )

    def test_files_must_be_utf_8(self) -> None:
        self.assert_fails({}, "a.json: not UTF-8 (invalid start byte at byte 1)", binary={"a.json": b'"\xff"'})
        self.assertEqual(_run({}, {"a.json": b"\xef\xbb\xbf{}"}).status, Status.PASS)

    def test_large_files_are_not_parsed(self) -> None:
        with mock.patch.object(module, "MAX_SIZE", 3):
            result = _run({"big.json": "[" * 10, "small.json": "{}"})
        self.assertEqual(
            result, Result.passed("1 data file parses (JSON: 1)", "big.json: not parsed, larger than 0 MiB")
        )

    def test_configuration_directories_are_parsed_and_other_hidden_ones_are_not(self) -> None:
        self.assert_fails({".github/workflows/ci.yml": "on: [push\n", ".cache/a.json": "{"}, mock.ANY)
        self.assertEqual(_run({".cache/a.json": "{", "deep/.hidden/b.json": "{"}).status, Status.PASS)

    def test_excluded_directories_are_not_parsed(self) -> None:
        self.assertEqual(_run({"tests/fixtures/broken.json": "{"}, exclude="tests/fixtures").status, Status.PASS)
