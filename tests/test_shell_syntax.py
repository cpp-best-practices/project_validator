"""The syntax of shell scripts: text to a tree with positions, before any command is derived from it."""

from __future__ import annotations

import re
import unittest

from project_validator.facts.shell_syntax import (
    Arithmetic,
    Case,
    Compounded,
    For,
    Function,
    Group,
    If,
    Item,
    Loop,
    Malformed,
    Script,
    Simple,
    Subshell,
    Substitution,
    Test,
    Verbatim,
    parse,
)
from project_validator.limits import SHELL_NESTING
from project_validator.parsing import Span


def _items(script: Script) -> list[Item]:
    items = [item for item in script.items if isinstance(item, Item)]
    if len(items) != len(script.items):
        raise AssertionError(f"malformed items in {script}")
    return items


def _command(text: str) -> object:
    """The only command of `text`, unwrapped from its item, list and pipeline."""
    [item] = _items(parse(text))
    [pipeline] = item.list.pipelines
    [command] = pipeline.commands
    return command.command if isinstance(command, Compounded) else command


def _argv(command: object) -> tuple[str, ...]:
    if not isinstance(command, Simple):
        raise AssertionError(f"not a simple command: {command}")
    return tuple(word.value for word in command.words)


class ListTests(unittest.TestCase):
    def test_items_and_or_lists_and_pipelines(self) -> None:
        [first, second] = _items(parse("a && b || c; d | e |& f &"))
        self.assertEqual(first.list.operators, ("&&", "||"))
        self.assertEqual(first.terminator, ";")
        [pipeline] = second.list.pipelines
        self.assertEqual(pipeline.operators, ("|", "|&"))
        self.assertEqual(second.terminator, "&")

    def test_a_newline_after_an_operator_continues_the_list(self) -> None:
        [item] = _items(parse("a &&\n  b |\n  c"))
        self.assertEqual(len(item.list.pipelines), 2)
        self.assertEqual(len(item.list.pipelines[1].commands), 2)

    def test_a_leading_bang_negates_the_pipeline(self) -> None:
        [item] = _items(parse("! grep -q x f"))
        self.assertTrue(item.list.pipelines[0].negated)


class CompoundTests(unittest.TestCase):
    def test_compound_commands(self) -> None:
        for text, kind in (
            ("( a; b )", Subshell),
            ("{ a; b; }", Group),
            ("if a; then b; elif c; then d; else e; fi", If),
            ("while a; do b; done", Loop),
            ("until a; do b; done", Loop),
            ("for x in a b; do c; done", For),
            ("case $x in a|b) c;; *) d;; esac", Case),
            ("[[ -f x && $y == z ]]", Test),
            ("(( i++ ))", Arithmetic),
            ("f() { a; }", Function),
            ("function f { a; }", Function),
        ):
            with self.subTest(text=text):
                self.assertIsInstance(_command(text), kind)

    def test_an_if_keeps_its_branches(self) -> None:
        command = _command("if a; then b; elif c; then d; else e; fi")
        if not isinstance(command, If):
            self.fail(command)
        self.assertEqual([clause.keyword for clause in command.clauses], ["if", "elif"])
        self.assertIsNotNone(command.otherwise)

    def test_a_case_keeps_its_patterns(self) -> None:
        command = _command("case $x in\n  a|b) c;;\n  *) d;;\nesac")
        if not isinstance(command, Case):
            self.fail(command)
        self.assertEqual([[word.value for word in item.patterns] for item in command.items], [["a", "b"], ["*"]])

    def test_a_for_keeps_its_variable_and_words(self) -> None:
        command = _command("for f in a 'b c'; do echo $f; done")
        if not isinstance(command, For) or command.words is None:
            self.fail(command)
        self.assertEqual((command.variable, [word.value for word in command.words]), ("f", ["a", "b c"]))

    def test_a_redirection_after_a_compound_command_is_its(self) -> None:
        [item] = _items(parse("while read l; do echo $l; done < input"))
        command = item.list.pipelines[0].commands[0]
        if not isinstance(command, Compounded):
            self.fail(command)
        self.assertEqual([redirection.operator for redirection in command.redirections], ["<"])


class LenientTests(unittest.TestCase):
    """What CI writes is not always a whole script: unclosed commands end with it, stray closing words are skipped."""

    def test_an_unclosed_compound_command_ends_with_the_script(self) -> None:
        command = _command("while true; do\n  make")
        if not isinstance(command, Loop):
            self.fail(command)
        self.assertEqual(len(command.body.items), 1)

    def test_a_closing_word_that_closes_nothing_is_skipped(self) -> None:
        self.assertEqual(
            [_argv(item.list.pipelines[0].commands[0]) for item in _items(parse("fi\nmake\ndone"))], [("make",)]
        )

    def test_an_if_without_then_is_a_condition_on_its_own_line(self) -> None:
        script = parse('if "a" equ "b" call x.bat\nopam init || exit /b 1')
        first, second = _items(script)
        command = first.list.pipelines[0].commands[0]
        if not isinstance(command, Compounded) or not isinstance(command.command, If):
            self.fail(command)
        self.assertEqual(len(command.command.clauses[0].condition.items), 1)
        self.assertEqual(_argv(second.list.pipelines[0].commands[0]), ("opam", "init"))


class WordTests(unittest.TestCase):
    def test_quotes_and_escapes_are_removed(self) -> None:
        self.assertEqual(_argv(_command("""echo 'a b' "c \\"d\\"" e\\ f""")), ("echo", "a b", 'c "d"', "e f"))

    def test_ansi_c_quoting_escapes_its_quote(self) -> None:
        self.assertEqual(_argv(_command("grep -- $'a\\'b' f")), ("grep", "--", "a'b", "f"))

    def test_substitutions_are_parsed_in_turn(self) -> None:
        command = _command('echo "$(git rev-parse HEAD)" `date` <(curl x)')
        if not isinstance(command, Simple):
            self.fail(command)
        substitutions = [part for word in command.words for part in word.substitutions()]
        self.assertEqual([part.written for part in substitutions], ["$(git rev-parse HEAD)", "`date`", "<(curl x)"])
        self.assertTrue(all(isinstance(part, Substitution) and part.script.items for part in substitutions))

    def test_arithmetic_and_opaque_text_are_kept_as_written(self) -> None:
        script = parse("echo $((1 + 2)) ${{ a == 'b' }}", opaque=re.compile(r"\$\{\{.*?\}\}"))
        [item] = _items(script)
        command = item.list.pipelines[0].commands[0]
        if not isinstance(command, Simple):
            self.fail(command)
        self.assertEqual([type(word.parts[0]) for word in command.words[1:]], [Verbatim, Verbatim])
        self.assertEqual(_argv(command), ("echo", "$((1 + 2))", "${{ a == 'b' }}"))

    def test_assignments_and_redirections_are_not_words(self) -> None:
        command = _command("CC=gcc A+=x arr=(a b) make 2>&1 >log <<EOF\nbody\nEOF")
        if not isinstance(command, Simple):
            self.fail(command)
        self.assertEqual([assignment.name for assignment in command.assignments], ["CC", "A", "arr"])
        self.assertEqual(_argv(command), ("make",))
        self.assertEqual([redirection.operator for redirection in command.redirections], [">&", ">", "<<"])
        self.assertEqual(command.redirections[0].descriptor, "2")
        self.assertEqual(command.redirections[2].body, "body\n")

    def test_a_quoted_operator_is_a_word(self) -> None:
        self.assertEqual(_argv(_command("cat a '>' b \\; c")), ("cat", "a", ">", "b", ";", "c"))


class PositionTests(unittest.TestCase):
    def test_nodes_say_where_they_are(self) -> None:
        script = parse("echo a\n  make all")
        _, second = _items(script)
        command = second.list.pipelines[0].commands[0]
        if not isinstance(command, Simple):
            self.fail(command)
        self.assertEqual(command.span, Span(2, 3, 2, 11))
        self.assertEqual(command.words[1].span, Span(2, 8, 2, 11))

    def test_logical_lines_join_continuations_and_skip_comments(self) -> None:
        text = "a \\\n  b\n# only a comment\n\nc # trailing\n"
        script = parse(text)
        self.assertEqual([text[start:end] for start, end in script.lines], ["a \\\n  b", "c # trailing"])


class MalformedTests(unittest.TestCase):
    def test_an_unclosed_quote_loses_its_line_only(self) -> None:
        script = parse('make\necho "open\nmore')
        self.assertIsInstance(script.items[0], Item)
        malformed = script.items[1]
        if not isinstance(malformed, Malformed):
            self.fail(malformed)
        self.assertEqual((malformed.reason, malformed.span.line), ("No closing quotation", 2))

    def test_an_unclosed_parameter_expansion_is_malformed(self) -> None:
        malformed = parse("make\necho ${X:-a\nls").items[1]
        if not isinstance(malformed, Malformed):
            self.fail(malformed)
        self.assertEqual(malformed.reason, "No closing brace")

    def test_substitutions_nest_at_most_the_limit_deep(self) -> None:
        most = SHELL_NESTING.most
        deep = "echo " + "$(" * most + "x" + ")" * most
        self.assertIsInstance(parse(deep).items[0], Item)
        deeper = "echo " + "$(" * (most + 1) + "x" + ")" * (most + 1)
        malformed = parse(f"make\n{deeper}\nls").items[1]
        if not isinstance(malformed, Malformed):
            self.fail(malformed)
        self.assertEqual(malformed.reason, SHELL_NESTING.reason)
        self.assertEqual(len(parse(f"make\n{deeper}\nls").items), 3)


if __name__ == "__main__":
    unittest.main()
