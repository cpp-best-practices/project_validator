"""lizard, which measures the functions of many languages at once and fails when one is longer than the limit it is
told. Each profile makes it its own, for the languages lizard measures (`function_length_limiters`)."""

import re

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.limits import FUNCTION_LENGTH, LIMITS, limited
from project_validator.facts.tools import Definition, Run, Tool

SUGGESTED_LIZARD = "lizard --length 30"

# A length limit, as lizard spells it: `-L 30`, `-L30`, `--length=30`, `-T length=30`, `-Tnloc=30`,
# `--Threshold nloc=30`. lizard's options are case-sensitive (`-l` selects a language), and with no limit it allows
# 1000 lines, which is no limit at all.
_LENGTH_THRESHOLD = re.compile(r"(?:length|nloc)=\d+")


def _limit(argv: tuple[str, ...]) -> bool:
    """Whether lizard's arguments set a function length limit."""
    for word, following in zip(argv, (*argv[1:], ""), strict=True):
        name, equals, value = word.partition("=")
        given = value if equals else following
        if (name in ("-L", "--length") and given.isdigit()) or (word.startswith("-L") and word[2:].isdigit()):
            return True
        if (name in ("-T", "--Threshold") and _LENGTH_THRESHOLD.fullmatch(given)) or (
            word.startswith("-T") and _LENGTH_THRESHOLD.fullmatch(word[2:])
        ):
            return True
    return False


def _lizard(command: Command, _facts: Facts) -> Run | None:
    """lizard, which limits function length when it is told a limit."""
    argv = resolved(command)
    return limited(active=_limit(argv)) if starts_with(argv, ("lizard",)) else None


def function_length_limiters(languages: frozenset[str]) -> tuple[Tool, ...]:
    """lizard, as a function length limiter of `languages`."""
    return (
        Tool(
            name="lizard",
            languages=languages,
            can={FUNCTION_LENGTH: {LIMITS: SUGGESTED_LIZARD}},
            claims=_lizard,
            definitions={FUNCTION_LENGTH: Definition(found=lambda _facts: (), describe="a --length limit")},
        ),
    )


__all__ = ["SUGGESTED_LIZARD", "function_length_limiters"]
