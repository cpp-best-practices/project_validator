"""The command line's surface: defaults, the options each flag sets, the choices argparse enforces, the help text, and
the shape of the JSON listings. The behaviour behind each option is tested where the option is used."""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import unittest
from pathlib import Path

from project_validator.cli import _options, _parser, main
from project_validator.core import DEFAULT_MAX_FILE_SIZE, Options
from tests.support import json_output


def _normalised(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _run(*arguments: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(arguments))
        except SystemExit as exit_:
            code = exit_.code if isinstance(exit_.code, int) else 1
    return code, out.getvalue(), err.getvalue()


class ParserDefaultsTests(unittest.TestCase):
    def test_every_option_has_its_documented_default(self) -> None:
        arguments = _parser().parse_args([])
        expected = {
            "path": Path("."),
            "only": [],
            "skip": [],
            "format": "text",
            "color": "auto",
            "exclude": [],
            "auxiliary": [],
            "strict": False,
            "plugin_dir": [],
            "build": False,
            "cmake": "cmake",
            "ctest": "ctest",
            "max_file_size": DEFAULT_MAX_FILE_SIZE,
            "allow_official_tags": False,
            "allow_unknown": False,
            "score": False,
            "html": None,
            "verbose": False,
            "tui": False,
            "explain": None,
            "list": False,
            "support_matrix": False,
        }
        for name, value in expected.items():
            with self.subTest(option=name):
                self.assertEqual(getattr(arguments, name), value)

    def test_the_defaults_make_the_default_options(self) -> None:
        self.assertEqual(_options(_parser().parse_args([])), Options())

    def test_each_check_option_reaches_the_options(self) -> None:
        arguments = _parser().parse_args(
            [
                *("--build", "--cmake", "my-cmake", "--ctest", "my-ctest", "--max-file-size", "2"),
                *("--allow-official-tags", "--allow-unknown"),
            ]
        )
        self.assertEqual(
            _options(arguments),
            Options(
                build=True,
                cmake="my-cmake",
                ctest="my-ctest",
                max_file_size=2 * 1024 * 1024,
                allow_official_tags=True,
                allow_unknown=True,
            ),
        )

    def test_repeatable_options_accumulate(self) -> None:
        arguments = _parser().parse_args(
            ["--only", "license", "--only", "tests-run", "--exclude", "a", "--exclude", "b/c", "--auxiliary", "docs"]
        )
        self.assertEqual(arguments.only, ["license", "tests-run"])
        self.assertEqual([str(path) for path in arguments.exclude], ["a", "b/c"])
        self.assertEqual(arguments.auxiliary, ["docs"])


class ParserChoicesTests(unittest.TestCase):
    def test_an_unknown_format_or_color_is_a_usage_error(self) -> None:
        for arguments in (("--format", "xml"), ("--color", "sometimes")):
            with self.subTest(arguments=arguments):
                code, _, errors = _run(*arguments)
                self.assertEqual(code, 2)
                self.assertIn("invalid choice", errors)

    def test_the_documented_choices_are_accepted(self) -> None:
        parser = _parser()
        for choice in ("text", "json", "markdown"):
            self.assertEqual(parser.parse_args(["--format", choice]).format, choice)
        for choice in ("auto", "always", "never"):
            self.assertEqual(parser.parse_args(["--color", choice]).color, choice)


class HelpTests(unittest.TestCase):
    def test_the_help_names_the_program_and_describes_it(self) -> None:
        code, output, _ = _run("--help")
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith("usage: project_validator"))
        self.assertIn("Validate a project's build, CI and tooling against best practices.", _normalised(output))

    def test_the_help_describes_every_option(self) -> None:
        parser = _parser()
        text = _normalised(parser.format_help())
        for action in parser._actions:
            if action.help in (None, argparse.SUPPRESS):
                continue
            with self.subTest(option=action.dest):
                self.assertIn(_normalised(str(action.help) % {"default": action.default}), text)
                if action.metavar:
                    self.assertIn(str(action.metavar), text)


class ListingFormatTests(unittest.TestCase):
    def test_list_as_json_is_indented_by_two(self) -> None:
        code, output, _ = _run("--list", "--format", "json")
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith('{\n  "format": "checks"'), output[:40])
        self.assertIsInstance(json_output(output, "checks"), list)

    def test_the_support_matrix_as_json_is_indented_by_two_and_ends_with_one_newline(self) -> None:
        code, output, _ = _run("--support-matrix", "--format", "json")
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith('{\n  "'), output[:40])
        self.assertTrue(output.endswith("}\n") and not output.endswith("\n\n"))
        self.assertIsInstance(json_output(output, "support-matrix"), dict)

    def test_the_support_matrix_as_markdown_ends_with_one_newline(self) -> None:
        _, output, _ = _run("--support-matrix")
        self.assertTrue(output.endswith("\n") and not output.endswith("\n\n"))

    def test_list_as_text_and_markdown_differ(self) -> None:
        _, text, _ = _run("--list")
        _, markdown, _ = _run("--list", "--format", "markdown")
        self.assertTrue(markdown.lstrip().startswith("|"), markdown[:40])
        self.assertFalse(text.lstrip().startswith("|"), text[:40])


if __name__ == "__main__":
    unittest.main()
