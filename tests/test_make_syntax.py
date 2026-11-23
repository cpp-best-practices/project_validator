"""The syntax of a makefile: lines to a tree with spans, without consulting any variable."""

from __future__ import annotations

import unittest

from project_validator.build_systems.make_syntax import (
    Assignment,
    Directive,
    Include,
    Node,
    RecipeLine,
    Rule,
    parse,
)
from project_validator.parsing import Span


def _shape(node: Node) -> object:
    """A node as nested tuples, without its span."""
    if isinstance(node, Assignment):
        return ("=", node.name, node.how, node.value)
    if isinstance(node, Rule):
        return ("rule", node.targets, node.prerequisites, node.recipe)
    if isinstance(node, RecipeLine):
        return ("recipe", node.text)
    if isinstance(node, Include):
        return ("include", node.files, node.optional)
    if isinstance(node, Directive):
        return ("directive", node.text)
    return (
        "if",
        tuple(
            (branch.test, branch.arguments, tuple(_shape(found) for found in branch.body)) for branch in node.branches
        ),
        None if node.otherwise is None else tuple(_shape(found) for found in node.otherwise),
    )


def _tree(text: str) -> list[object]:
    return [_shape(node) for node in parse(text).nodes]


def _errors(text: str) -> list[tuple[str, int | None]]:
    return [(error.message, error.line) for error in parse(text).errors]


class TreeTests(unittest.TestCase):
    def test_assignments_rules_recipes_and_includes(self) -> None:
        text = "CC := gcc\nall: build ; echo inline\n\t@$(CC) -o app\n-include local.mk\n"
        self.assertEqual(
            _tree(text),
            [
                ("=", "CC", ":=", "gcc"),
                ("rule", ("all",), ("build",), "echo inline"),
                ("recipe", "@$(CC) -o app"),
                ("include", "local.mk", True),
            ],
        )

    def test_every_assignment_operator_and_its_modifiers(self) -> None:
        text = "A = 1\nB ::= 2\nC ?= 3\nD += 4\nE != date\noverride F = 5\nexport G := 6\nH = a b # note\n"
        self.assertEqual(
            [node.how for node in parse(text).nodes if isinstance(node, Assignment)],
            ["=", "::=", "?=", "+=", "!=", "=", ":=", "="],
        )
        assignments = [node for node in parse(text).nodes if isinstance(node, Assignment)]
        self.assertEqual((assignments[5].override, assignments[6].export), (True, True))
        self.assertEqual(assignments[7].value, "a b")

    def test_a_define_holds_its_lines_as_the_value_not_as_rules(self) -> None:
        """A `define` body is a variable's value: its `name:` lines are no rules, its `X = y` no assignments."""
        text = "define RECIPE =\nlint:\n\tclang-format x\nY = z\nendef\nall:\n"
        self.assertEqual(
            _tree(text),
            [("=", "RECIPE", "=", "lint:\n\tclang-format x\nY = z"), ("rule", ("all",), (), "")],
        )

    def test_conditionals_nest_with_their_branches(self) -> None:
        text = (
            "ifeq ($(OS),Windows_NT)\nEXE = .exe\nelse ifdef MSYS\nEXE = .msys\nelse\n"
            "ifndef DEBUG\nOPT = -O2\nendif\nendif\n"
        )
        self.assertEqual(
            _tree(text),
            [
                (
                    "if",
                    (
                        ("ifeq", "($(OS),Windows_NT)", (("=", "EXE", "=", ".exe"),)),
                        ("ifdef", "MSYS", (("=", "EXE", "=", ".msys"),)),
                    ),
                    (("if", (("ifndef", "DEBUG", (("=", "OPT", "=", "-O2"),)),), None),),
                )
            ],
        )

    def test_lines_indented_with_spaces_are_read_as_written_unindented(self) -> None:
        """Makefiles indent what a conditional holds (neovim's `  CMAKE := cmake`); only a tab starts a recipe line."""
        text = "ifdef WIN\n  CC := cl\n  include win.mk\n  all: app\n\tlink app\nendif\n"
        self.assertEqual(
            _tree(text),
            [
                (
                    "if",
                    (
                        (
                            "ifdef",
                            "WIN",
                            (
                                ("=", "CC", ":=", "cl"),
                                ("include", "win.mk", False),
                                ("rule", ("all",), ("app",), ""),
                                ("recipe", "link app"),
                            ),
                        ),
                    ),
                    None,
                )
            ],
        )

    def test_a_recipe_line_inside_a_conditional_is_a_node_of_its_own(self) -> None:
        """Which rule it belongs to is the evaluation's to say: the rule written before the conditional."""
        text = "all:\nifeq ($(V),1)\n\techo verbose\nelse\n\t@echo quiet\nendif\n"
        self.assertEqual(
            _tree(text),
            [
                ("rule", ("all",), (), ""),
                ("if", (("ifeq", "($(V),1)", (("recipe", "echo verbose"),)),), (("recipe", "@echo quiet"),)),
            ],
        )

    def test_continued_lines_are_joined_and_span_from_their_first_line(self) -> None:
        tree = parse("a: \\\n  b \\\n  c\n\techo \\\n\t  done\n")
        rule, recipe = tree.nodes
        self.assertIsInstance(rule, Rule)
        self.assertEqual((rule.prerequisites, rule.span), (("b", "c"), Span(1, 1, 3, 4)))  # type: ignore[union-attr]
        self.assertEqual((recipe.text.split(), recipe.span.line), (["echo", "done"], 4))  # type: ignore[union-attr]

    def test_comments_and_blank_lines_are_not_nodes_and_other_lines_are_directives(self) -> None:
        self.assertEqual(
            _tree("# note\n\nvpath %.c src\n.PHONY: all\n"),
            [("directive", "vpath %.c src"), ("rule", (".PHONY",), ("all",), "")],
        )

    def test_a_conditional_spans_to_its_endif(self) -> None:
        [conditional] = parse("ifdef X\nA = 1\nelse\nA = 2\nendif\n").nodes
        self.assertEqual(conditional.span, Span(1, 1, 5, 6))
        [unclosed] = parse("ifdef X\nA = 1\n").nodes
        self.assertEqual(unclosed.span, Span(1, 1, 2, 6))

    def test_a_well_formed_makefile_has_no_errors(self) -> None:
        self.assertEqual(_errors("ifdef X\nA = 1\nelse\nA = 2\nendif\ndefine B\nb\nendef\n"), [])


class RecoveryTests(unittest.TestCase):
    """A makefile with an error reports it, with its line, and keeps what can still be read."""

    def test_a_conditional_never_closed_ends_with_the_makefile(self) -> None:
        self.assertEqual(_tree("ifdef X\nA = 1\n"), [("if", (("ifdef", "X", (("=", "A", "=", "1"),)),), None)])
        self.assertEqual(_errors("ifdef X\nA = 1\n"), [("the ifdef is never closed with endif", 1)])

    def test_else_and_endif_with_no_conditional_close_nothing(self) -> None:
        self.assertEqual(_tree("else\nA = 1\nendif\n"), [("=", "A", "=", "1")])
        self.assertEqual(_errors("else\nA = 1\nendif\n"), [("else closes nothing", 1), ("endif closes nothing", 3)])

    def test_a_define_never_ended_holds_the_rest_of_the_makefile(self) -> None:
        self.assertEqual(_tree("define X\na: b\n"), [("=", "X", "=", "a: b")])
        self.assertEqual(_errors("define X\na: b\n"), [("the define is never closed with endef", 1)])

    def test_a_second_else_is_reported_and_its_lines_kept_in_the_last_branch(self) -> None:
        tree = _tree("ifdef X\nA = 1\nelse\nA = 2\nelse\nA = 3\nendif\n")
        self.assertEqual(
            tree, [("if", (("ifdef", "X", (("=", "A", "=", "1"),)),), (("=", "A", "=", "2"), ("=", "A", "=", "3")))]
        )
        self.assertEqual(
            _errors("ifdef X\nA = 1\nelse\nA = 2\nelse\nA = 3\nendif\n"), [("the ifdef has a second else", 5)]
        )


if __name__ == "__main__":
    unittest.main()
