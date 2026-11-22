"""Words of an embedded command line (an action's inputs, an alias, a re-joined argv), split and joined in one place,
`project_validator.facts.shell`; a line that does not split is a syntax error, and unknown, never a crash."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from project_validator.facts import Command, Unknown
from project_validator.facts.shell import ShellSyntaxError, command_line, quoted, split_words
from project_validator.parsing import ParseError
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

PACKAGE = Path(__file__).parent.parent / "project_validator"


class WordsTests(unittest.TestCase):
    def test_words_split_as_a_shell_splits_them(self) -> None:
        self.assertEqual(split_words('check "src dir" --fix'), ("check", "src dir", "--fix"))
        self.assertEqual(split_words(""), ())

    def test_comments_are_kept_unless_asked_for(self) -> None:
        self.assertEqual(split_words("a # b"), ("a", "#", "b"))
        self.assertEqual(split_words("a # b", comments=True), ("a",))

    def test_an_unclosed_quote_is_a_syntax_error(self) -> None:
        with self.assertRaises(ShellSyntaxError) as raised:
            split_words('check "src')
        self.assertIsInstance(raised.exception, ParseError)
        self.assertEqual(str(raised.exception), "No closing quotation")

    def test_joined_words_split_back_into_the_same_words(self) -> None:
        argv = ("cmake", "-DX=a b", "it's")
        self.assertEqual(split_words(command_line(argv)), argv)
        self.assertEqual(quoted("a b"), "'a b'")


class ActionInputTests(unittest.TestCase):
    def test_an_action_input_that_does_not_split_is_unknown_not_a_crash(self) -> None:
        step = {"uses": "astral-sh/ruff-action@v3", "with": {"args": 'check "src'}}
        workflow = {"on": "push", "jobs": {"t": {"runs-on": "ubuntu-latest", "steps": [step]}}}
        with temp_project({GITHUB_WORKFLOW: json.dumps(workflow), "a.py": "x = 1\n"}) as root:
            facts = make_context(root).facts
        self.assertNotIn("ruff", [command.argv[0] for command in facts.of(Command)])
        reasons = [unknown.reason for unknown in facts.of(Unknown) if unknown.subject.startswith("the action")]
        self.assertEqual(reasons, ["its inputs do not split into words: No closing quotation"])


def _workflow(run: str) -> str:
    return json.dumps({"on": "push", "jobs": {"t": {"runs-on": "ubuntu-latest", "steps": [{"run": run}]}}})


class EmbeddedLineTests(unittest.TestCase):
    def test_code_whose_commands_do_not_split_is_unknown_not_a_crash(self) -> None:
        files = {GITHUB_WORKFLOW: _workflow("julia -e 'run(`echo \"a`)'"), "Project.toml": "name = 'X'\n"}
        with temp_project(files) as root:
            facts = make_context(root).facts
        reasons = [unknown.reason for unknown in facts.of(Unknown) if "julia" in unknown.subject]
        self.assertEqual(reasons, ["what it runs does not split into words: No closing quotation"])

    def test_settings_that_do_not_split_make_the_tool_run_unknown_not_a_crash(self) -> None:
        pyproject = "[tool.pytest.ini_options]\naddopts = '--cov \"x'\n"
        files = {GITHUB_WORKFLOW: _workflow("pytest"), "pyproject.toml": pyproject, "a.py": "x = 1\n"}
        with temp_project(files) as root:
            facts = make_context(root).facts
        unknowns = [unknown for unknown in facts.of(Unknown) if unknown.tools == ("pytest-cov",)]
        self.assertEqual(
            [(unknown.subject, unknown.reason) for unknown in unknowns],
            [("the pytest-cov run", "a command line it reads does not split into words: No closing quotation")],
        )


class OneSplitterTests(unittest.TestCase):
    def test_only_the_shell_reader_uses_shlex(self) -> None:
        users = sorted(
            str(path.relative_to(PACKAGE))
            for path in PACKAGE.rglob("*.py")
            if "shlex" in path.read_text(encoding="utf-8") and path != PACKAGE / "facts" / "shell.py"
        )
        self.assertEqual(users, [])
