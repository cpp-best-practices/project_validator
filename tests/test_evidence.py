import unittest

from project_validator.evidence import json_value
from tests.support import make_context, temp_project


class JsonValueTests(unittest.TestCase):
    def test_a_file_that_does_not_parse_has_no_values(self) -> None:
        with temp_project({"package.json": '{"license": '}) as root:
            self.assertIsNone(json_value(make_context(root), "package.json", "license"))

    def test_a_value_below_one_that_is_not_an_object_is_missing(self) -> None:
        with temp_project({"package.json": '{"license": "MIT"}'}) as root:
            self.assertIsNone(json_value(make_context(root), "package.json", "license", "type"))

    def test_json_with_comments_is_read_when_asked(self) -> None:
        with temp_project({"deno.jsonc": '{\n  // the license\n  "license": "MIT",\n}\n'}) as root:
            self.assertEqual(json_value(make_context(root), "deno.jsonc", "license", comments=True), "MIT")
