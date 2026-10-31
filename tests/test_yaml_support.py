import unittest
from unittest import mock

from project_validator import yaml_support


class YamlSupportTests(unittest.TestCase):
    def test_a_missing_install_is_detected(self) -> None:
        with mock.patch("importlib.import_module", side_effect=ImportError):
            self.assertIsNone(yaml_support._import_yaml())

    def test_loading_without_pyyaml_explains_how_to_install_it(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None), self.assertRaises(yaml_support.YamlError) as raised:
            yaml_support.load("a: 1")
        self.assertEqual(str(raised.exception), yaml_support.MISSING_MESSAGE)

    def test_invalid_yaml_is_reported_on_one_line(self) -> None:
        with self.assertRaises(yaml_support.YamlError) as raised:
            yaml_support.load("a: [unclosed\n")
        self.assertNotIn("\n", str(raised.exception))
