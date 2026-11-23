"""The commands derived from a shell script's tree: what the line splitter got wrong, and the tree gets right."""

from __future__ import annotations

import re
import unittest

from project_validator.facts.shell import POWERSHELL, ShellCommand, Unsplittable, split_script
from project_validator.limits import SHELL_NESTING
from project_validator.parsing import Span

MAKE_VARIABLE = re.compile(r"\$(?:\([^()]*\)|\{[^{}]*\}|[^({$\s])")


def _commands(script: str, opaque: re.Pattern[str] | None = None) -> list[ShellCommand]:
    return [found for found in split_script(script, opaque) if isinstance(found, ShellCommand)]


def _argvs(script: str) -> list[tuple[str, ...]]:
    return [command.argv for command in _commands(script)]


class StructureTests(unittest.TestCase):
    def test_case_patterns_are_not_commands(self) -> None:
        script = 'case "$x" in\n  OWNER|MEMBER)\n    echo ok\n    ;;\n  *)\n    echo no\n    ;;\nesac\n'
        self.assertEqual(_argvs(script), [("echo", "ok"), ("echo", "no")])

    def test_an_array_over_several_lines_is_an_assignment(self) -> None:
        script = 'args=(\n  --dist out\n  --title "$V"\n)\npython build.py "${args[@]}"\n'
        self.assertEqual(_argvs(script), [("python", "build.py", "${args[@]}")])

    def test_an_appending_assignment_is_no_command(self) -> None:
        self.assertEqual(_argvs('archives+=("$a")\nX+=1 make\n'), [("make",)])

    def test_an_array_given_to_declare_is_one_argument(self) -> None:
        commands = _commands("declare -a V=(\n  '1.7'\n  $(ls)\n)\nlocal x=(a b)\n")
        self.assertEqual(
            [(command.argv, command.nested) for command in commands],
            [(("ls",), True), (("declare", "-a", "V=(1.7 $(ls))"), False), (("local", "x=(a b)"), False)],
        )
        self.assertFalse([found for found in split_script("declare -a V=(a b)") if isinstance(found, Unsplittable)])

    def test_a_function_definition_is_not_a_command_but_its_body_runs(self) -> None:
        self.assertEqual(_argvs("warn () {\n  echo x\n}\nf() { ls; }\n"), [("echo", "x"), ("ls",)])

    def test_an_arithmetic_command_runs_nothing(self) -> None:
        self.assertEqual(_argvs("(( i++ ))\nif (( $A < $B )); then exit 1; fi\n"), [("exit", "1")])

    def test_a_condition_over_several_lines_is_one_condition(self) -> None:
        script = 'if [ -n "$A" ] ||\n   ! git merge-base --is-ancestor a b; then\n  exit 1\nfi\n'
        conditions = [command.condition for command in _commands(script)]
        self.assertEqual(conditions, ["if", "if", ""])

    def test_a_negated_group_negates_every_command_in_it(self) -> None:
        commands = _commands("! (report | tee summary | grep ':x:')")
        self.assertEqual([command.condition for command in commands], ["!", "!", "!"])


class WordTests(unittest.TestCase):
    def test_an_apostrophe_in_a_comment_does_not_quote_what_follows(self) -> None:
        script = '# Extract the binary\'s paths\nTARGET=$(dirname "$LIB")\n'
        self.assertEqual(
            [(command.argv, command.env, command.nested) for command in _commands(script)],
            [(("dirname", "$LIB"), (), True)],
        )

    def test_a_quoted_parenthesis_does_not_close_a_substitution(self) -> None:
        script = "opens=$(grep -cE '(open|openat)\\([^)]*\"x\"' log || true)\necho \"$(printf ')')\"\n"
        self.assertEqual(
            [command.argv for command in _commands(script)],
            [("grep", "-cE", '(open|openat)\\([^)]*"x"', "log"), ("true",), ("printf", ")"), ("echo", "$(printf ')')")],
        )

    def test_a_parameter_expansion_is_one_word_and_runs_its_substitutions(self) -> None:
        commands = _commands('make -j ${JOBS:-$(nproc)} ${MSG:-"a b"} ${X:-a b}\n')
        self.assertEqual(
            [(command.argv, command.nested) for command in commands],
            [(("nproc",), True), (("make", "-j", "${JOBS:-$(nproc)}", "${MSG:-a b}", "${X:-a b}"), False)],
        )

    def test_escapes_in_a_quoted_parameter_expansion_are_kept(self) -> None:
        self.assertEqual(_argvs('echo "${tag//-/\\~}" ${tag//-/\\~}\n'), [("echo", "${tag//-/\\~}", "${tag//-/~}")])

    def test_an_ansi_c_quote_inside_a_substitution_does_not_unbalance_it(self) -> None:
        commands = _commands("x=$(rg -o $'[\\'`]' f | sort)\n")
        self.assertEqual([(command.argv[0], command.nested) for command in commands], [("rg", True), ("sort", True)])

    def test_a_number_before_a_spaced_redirection_is_an_argument(self) -> None:
        self.assertEqual(_argvs("report -p 0 >> summary\n"), [("report", "-p", "0")])

    def test_a_process_substitution_runs_its_command(self) -> None:
        commands = _commands("bash <(curl https://x/install.sh)\n")
        self.assertEqual(
            [(command.argv, command.nested) for command in commands],
            [(("curl", "https://x/install.sh"), True), (("bash", "<(curl https://x/install.sh)"), False)],
        )

    def test_a_fallback_names_opaque_text_as_written(self) -> None:
        [first, _] = _commands("test -f a || $(call GET,x)\n", MAKE_VARIABLE)
        self.assertEqual(first.fallback, "$(call GET,x)")


class PowerShellTests(unittest.TestCase):
    def test_an_assignment_is_no_command_but_a_command_it_assigns_runs(self) -> None:
        script = '$workspace = "C:\\" + (Split-Path $env:X -Leaf)\n$n = 3\n$r = gh issue create -t x\n$a += "b"\n'
        found = [found.argv for found in split_script(script, dialect=POWERSHELL) if isinstance(found, ShellCommand)]
        self.assertEqual(found, [("gh", "issue", "create", "-t", "x")])


class ErrorTests(unittest.TestCase):
    """A script with an error yields the error, where it is, and every command that can still be read."""

    def _stream(self, script: str) -> list[object]:
        return [
            found.argv if isinstance(found, ShellCommand) else (found.reason, found.line, found.span)
            for found in split_script(script)
        ]

    def test_an_unclosed_quote_is_reported_and_the_rest_is_read(self) -> None:
        self.assertEqual(
            self._stream('make\necho "open\nls\n'),
            [("make",), ("No closing quotation", 'echo "open', Span(2, 6)), ("echo", "open"), ("ls",)],
        )

    def test_an_unclosed_compound_command_is_reported_and_its_commands_are_read(self) -> None:
        self.assertEqual(
            self._stream("if [ -f x ]; then\n  make\n"),
            [("the if is never closed with fi", "if [ -f x ]; then", Span(1, 1)), ("[", "-f", "x", "]"), ("make",)],
        )

    def test_a_line_nested_too_deeply_keeps_its_command(self) -> None:
        deep = "echo " + "$(" * 60 + "x" + ")" * 60
        found = list(split_script(f"cmake --build build\nctest\n{deep}\n"))
        top = [item.argv for item in found if isinstance(item, ShellCommand) and not item.nested]
        self.assertEqual(top, [("cmake", "--build", "build"), ("ctest",), ("echo", deep[5:])])
        self.assertIn(SHELL_NESTING.reason, [item.reason for item in found if isinstance(item, Unsplittable)])


class PartlyReadTests(unittest.TestCase):
    """What the parser cannot follow may be its own limit, not the script's error: it is noted, never unknown, and
    what could be read is used."""

    def test_a_script_read_in_part_is_noted_not_unknown(self) -> None:
        from project_validator.facts import Command, Origin, PartlyRead, Unknown
        from project_validator.facts.expansion import script_facts

        origin = Origin(path=".github/workflows/ci.yml", at=("jobs", "test", "steps", 0, "run"))
        facts = list(script_facts('make\necho "open\nctest\n', job="test", origin=origin))
        self.assertEqual(
            [fact.argv for fact in facts if isinstance(fact, Command)], [("make",), ("echo", "open"), ("ctest",)]
        )
        self.assertFalse([fact for fact in facts if isinstance(fact, Unknown)])
        [noted] = [fact for fact in facts if isinstance(fact, PartlyRead)]
        self.assertEqual((noted.subject, noted.reason), ("the command 'echo \"open'", "No closing quotation at 2:6"))

    def test_a_script_nothing_can_be_read_from_is_unknown(self) -> None:
        """When the parser learns nothing at all from a script, what it runs is not known: that is unknown."""
        from project_validator.facts import Command, Origin, PartlyRead, Unknown
        from project_validator.facts.expansion import script_facts

        facts = list(script_facts("fi\ndone\n", job="test", origin=Origin(path="ci.sh")))
        self.assertFalse([fact for fact in facts if isinstance(fact, (Command, PartlyRead))])
        self.assertEqual(
            [(fact.subject, fact.reason) for fact in facts if isinstance(fact, Unknown)],
            [("the script", "nothing in it could be read: fi closes nothing at 1:1; done closes nothing at 2:1")],
        )


if __name__ == "__main__":
    unittest.main()
