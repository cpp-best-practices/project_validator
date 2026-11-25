"""How far the readers follow what nests: every limit in one place, each with the reason a reader gives when it is
reached. Past a limit a reader never cuts off silently: what lies deeper is unknown, and says why (`Limit.reason`).

Each limit is tested at its value and one past it (tests/test_limits.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limit:
    """A reader follows `what` at most `most` levels deep."""

    what: str
    most: int

    def allows(self, levels: int) -> bool:
        """Whether a chain `levels` long is followed."""
        return levels <= self.most

    @property
    def reason(self) -> str:
        return f"{self.what} nest more than {self.most} levels deep"


# CMake functions and macros calling each other, include() and add_subdirectory().
CMAKE_NESTING = Limit("calls, includes or subdirectories", 24)
# GitLab reads at most this many levels of includes, `extends` and `!reference` tags.
GITLAB_INCLUDES = Limit("its includes", 10)
GITLAB_EXTENDS = Limit("the templates it extends", 10)
GITLAB_REFERENCES = Limit("its !reference tags", 10)
# The rc files a .bazelrc imports, and those they import in turn.
BAZELRC_IMPORTS = Limit("its imports", 10)
# The makefiles a makefile includes, and those they include in turn.
MAKE_INCLUDES = Limit("its includes", 10)
# GitHub runs at most this many levels of reusable workflows; composite actions are followed as deep.
REUSABLE_WORKFLOWS = Limit("the reusable workflows it calls", 4)
COMPOSITE_ACTIONS = Limit("the composite actions it uses", 4)
# The local tsconfig files a configuration extends, followed for its strictness.
TSCONFIG_EXTENDS = Limit("the configurations it extends", 4)
# GitHub's runner rejects an expression whose tree is deeper (its MaxDepth); parentheses are held to it too.
GITHUB_EXPRESSION_NESTING = Limit("its operators, calls and parentheses", 50)
# Command substitutions inside command substitutions, as deep as a shell script is split.
SHELL_NESTING = Limit("its command substitutions", 50)
# Compound commands ({ }, ( ), if, while, until, for, case, functions) inside each other in one script, read past this
# without nesting further. With the substitutions, it holds the reader's recursion well inside Python's stack.
SHELL_COMPOUNDS = Limit("its compound commands", 30)
# Deeper than this, JSON is read without recursion: how deep Python's own decoder goes depends on the interpreter, and
# a report must not (JSONTestSuite's 100000-deep arrays).
JSON_NESTING = Limit("its arrays and objects", 500)
