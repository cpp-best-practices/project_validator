"""Text-search helpers used by the checks and by heuristic CI parsing."""

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    regex: re.Pattern[str]


def pattern(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.IGNORECASE))


def matching_names(texts: Iterable[str], patterns: Iterable[Pattern]) -> list[str]:
    """Names of the patterns found in any text, in pattern order and without duplicates."""
    texts = tuple(texts)
    found = (p.name for p in patterns if any(p.regex.search(text) for text in texts))
    return list(dict.fromkeys(found))


_CMAKE_TOKENS = re.compile(
    r"""
      (?P<quoted>"(?:\\.|[^"\\])*")
    | (?P<bracket_comment>\#\[(?P<comment_level>=*)\[.*?\](?P=comment_level)\])
    | (?P<line_comment>\#[^\n]*)
    | (?P<bracket_argument>\[(?P<argument_level>=*)\[.*?\](?P=argument_level)\])
    """,
    re.VERBOSE | re.DOTALL,
)


def _keep_unless_comment(match: re.Match[str]) -> str:
    return "" if match["bracket_comment"] or match["line_comment"] else match[0]


def strip_cmake_comments(text: str) -> str:
    return _CMAKE_TOKENS.sub(_keep_unless_comment, text)
