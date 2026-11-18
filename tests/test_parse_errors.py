"""Where a reader says a file breaks, and what it says: users see these lines, columns and messages, so they are
asserted, not just that an error is raised."""

from __future__ import annotations

import sys
import unittest

from project_validator.build_systems.cmake.ctest import BuildError, _run
from project_validator.build_systems.meson.syntax import MesonSyntaxError
from project_validator.build_systems.meson.syntax import parse as parse_meson
from project_validator.ecosystems.data import _check_deep_json
from project_validator.ecosystems.docker.dockerfile import parse as parse_dockerfile
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError
from project_validator.ecosystems.haskell.cabal import parse as parse_cabal
from project_validator.facts.wellformed import ParseError
from project_validator.text import JsonSyntaxError, check_json


def _json_error(text: str) -> tuple[str, int, int]:
    try:
        check_json(text)
    except JsonSyntaxError as error:
        return str(error), error.line, error.column
    raise AssertionError(f"{text!r} parsed")


def _dockerfile_error(text: str) -> tuple[str, int | None, int | None]:
    try:
        parse_dockerfile("Dockerfile", text.encode())
    except ParseError as error:
        return error.message, error.line, error.column
    raise AssertionError(f"{text!r} parsed")


class JsonPositionTests(unittest.TestCase):
    def test_the_line_and_column_of_the_token_that_breaks_it(self) -> None:
        for text, line, column in (("[1,\n  ]", 2, 3), ('{\n  "a" 1\n}', 2, 7), ("[1,\n2,\n\n   ,3]", 4, 4)):
            with self.subTest(text=text):
                self.assertEqual(_json_error(text), ("malformed JSON", line, column))

    def test_an_unfinished_value_breaks_at_its_end(self) -> None:
        self.assertEqual(_json_error("  [1, 2"), ("malformed JSON", 1, 8))

    @unittest.expectedFailure  # upstream #306
    def test_content_after_the_value_breaks_where_it_starts(self) -> None:
        self.assertEqual(_json_error("[1]\n x"), ("malformed JSON", 2, 2))
        self.assertEqual(_json_error('{"a": 1}  ,'), ("malformed JSON", 1, 11))

    def test_deep_json_keeps_the_position(self) -> None:
        with self.assertRaises(ParseError) as raised:
            _check_deep_json("[1,\n  ]")
        self.assertEqual(
            (raised.exception.message, raised.exception.line, raised.exception.column), ("malformed JSON", 2, 3)
        )


class DockerfilePositionTests(unittest.TestCase):
    def test_each_problem_is_reported_at_its_instruction(self) -> None:
        cases = {
            "FROM alpine\nBOGUS x\n": ("unknown instruction BOGUS", 2, 1),
            "FROM alpine\n\nRUN\n": ("RUN has no arguments", 3, 1),
            "ARG A=1\nARG B=2\n": ("no build stage: a Dockerfile needs a FROM", 2, 1),
            "ARG A=1\nRUN x\nFROM a\n": ("the first instruction is RUN, not FROM", 2, 1),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_dockerfile_error(text), expected)

    def test_an_empty_dockerfile_has_no_position(self) -> None:
        self.assertEqual(
            _dockerfile_error("# only a comment\n"), ("no instructions: a Dockerfile starts with FROM", None, None)
        )


class OtherReaderErrorTests(unittest.TestCase):
    def test_meson_nested_too_deeply_names_the_line(self) -> None:
        with self.assertRaises(MesonSyntaxError) as raised:
            parse_meson("x = 1\ny = " + "(" * 100_000 + "1" + ")" * 100_000 + "\n")
        self.assertEqual(str(raised.exception), "line 2: nested too deeply to read")

    def test_cabal_tab_indentation_names_the_line(self) -> None:
        with self.assertRaises(CabalSyntaxError) as raised:
            parse_cabal("name: x\n\nlibrary\n\tbuild-depends: base\n")
        self.assertEqual(str(raised.exception), "line 4: tab in indentation")


class BuildCommandErrorTests(unittest.TestCase):
    def test_a_missing_program_is_named(self) -> None:
        with self.assertRaises(BuildError) as raised:
            _run(["/nonexistent/ctest-for-a-test", "--version"])
        self.assertTrue(str(raised.exception).startswith("could not run /nonexistent/ctest-for-a-test: "))

    def test_a_failing_command_reports_its_last_five_lines_of_errors(self) -> None:
        script = "import sys\nfor i in range(8): print(f'line {i}', file=sys.stderr)\nsys.exit(3)"
        command = [sys.executable, "-c", script]
        with self.assertRaises(BuildError) as raised:
            _run(command)
        message = str(raised.exception)
        self.assertEqual(message, f"`{' '.join(command)}` failed: line 3 | line 4 | line 5 | line 6 | line 7")

    def test_a_succeeding_command_returns_its_output_as_text(self) -> None:
        self.assertEqual(_run([sys.executable, "-c", "print('ok')"]), "ok\n")


if __name__ == "__main__":
    unittest.main()
