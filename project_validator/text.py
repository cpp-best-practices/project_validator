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


def found_and_missing(texts: Iterable[str], patterns: Iterable[Pattern]) -> tuple[list[str], list[str]]:
    """Names of the patterns found in any text, and of those found in none, both in pattern order."""
    texts = tuple(texts)
    found: list[str] = []
    missing: list[str] = []
    for p in patterns:
        (found if any(p.regex.search(text) for text in texts) else missing).append(p.name)
    return found, missing


# A string, a comment, or a comma that only whitespace separates from the closing bracket.
_JSONC_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|,(?=\s*[}\]])', re.DOTALL)


def _blank_unless_string(match: re.Match[str]) -> str:
    token = match[0]
    return token if token.startswith('"') else re.sub(r"[^\n]", " ", token)


def strip_json_comments(text: str) -> str:
    """JSON with comments and trailing commas as plain JSON; comments become blanks, so positions are kept."""
    return _JSONC_TOKENS.sub(_blank_unless_string, _JSONC_TOKENS.sub(_blank_unless_string, text))
