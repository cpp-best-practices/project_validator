"""The ignore files of the version control systems (Git, Mercurial, Bazaar, Fossil), read as `IgnoreEntry` facts.

Jujutsu reads .gitignore too; Subversion keeps its ignores in svn:ignore properties, which are not files.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from project_validator.facts import Fact, Origin
from project_validator.facts.outputs import IgnoreEntry, Syntax
from project_validator.facts.settings import SettingsReader

type Parsed = tuple[str, str, Syntax]


def _glob(written: str, pattern: str | None = None) -> Parsed:
    return written, written if pattern is None else pattern, Syntax.GLOB


def _rooted_glob(written: str, pattern: str) -> Parsed:
    return _glob(written, "/" + pattern.lstrip("/"))


def _regex(written: str, pattern: str) -> Parsed:
    return written, pattern, Syntax.REGEX


def _rule_lines(text: str) -> Iterator[str]:
    """The stripped lines of an ignore file; blank lines and comments ignore nothing."""
    lines = (line.strip() for line in text.splitlines())
    return (line for line in lines if line and not line.startswith("#"))


def _git_entries(text: str) -> Iterator[Parsed]:
    """Negations re-include what earlier entries ignored, so they ignore nothing."""
    return (_glob(line) for line in _rule_lines(text) if not line.startswith("!"))


MERCURIAL_SYNTAXES: dict[str, Callable[[str, str], Parsed]] = {
    "re": _regex,
    "regexp": _regex,
    "relre": _regex,
    "glob": _glob,
    "relglob": _glob,
    "rootglob": _rooted_glob,
    "path": _rooted_glob,
    "relpath": _rooted_glob,
}

MERCURIAL_UNFOLLOWED = frozenset({"include", "subinclude", "listfile", "listfile0", "rootfilesin", "set"})

MERCURIAL_SYNTAX_LINE = re.compile(r"syntax:\s*(?P<syntax>\S+)")


def _mercurial_entry(line: str, syntax: str) -> Parsed | None:
    """An entry in the current `syntax`, unless a prefix (e.g. glob:) names its own; includes are not followed."""
    prefix, separator, pattern = line.partition(":")
    if separator and prefix in MERCURIAL_SYNTAXES:
        return MERCURIAL_SYNTAXES[prefix](line, pattern)
    if separator and prefix in MERCURIAL_UNFOLLOWED:
        return None
    entry = MERCURIAL_SYNTAXES.get(syntax)
    return None if entry is None else entry(line, line)


def _mercurial_entries(text: str) -> Iterator[Parsed]:
    """A .hgignore holds regular expressions until a `syntax:` line switches the syntax of the lines that follow."""
    syntax = "regexp"
    for line in _rule_lines(text):
        if switch := MERCURIAL_SYNTAX_LINE.fullmatch(line):
            syntax = switch["syntax"]
        elif entry := _mercurial_entry(line, syntax):
            yield entry


def _bazaar_entry(line: str) -> Parsed | None:
    """RE: marks a regular expression, ./ roots a glob, !! forces an ignore and a single ! is an exception."""
    rule = line.removeprefix("!!")
    if rule.startswith("!"):
        return None
    if rule[:3].upper() == "RE:":
        return _regex(line, rule[3:])
    if rule.startswith("./"):
        return _rooted_glob(line, rule[2:])
    return _glob(line, rule)


def _bazaar_entries(text: str) -> Iterator[Parsed]:
    return (entry for line in _rule_lines(text) if (entry := _bazaar_entry(line)))


FOSSIL_GLOB_SEPARATORS = re.compile(r"[\s,]+")


def _fossil_entries(text: str) -> Iterator[Parsed]:
    """Fossil globs are separated by commas or whitespace and may be quoted."""
    globs = (glob.strip("'\"") for glob in FOSSIL_GLOB_SEPARATORS.split(text))
    return (_glob(glob) for glob in globs if glob)


def _reader(path: str, entries: Callable[[str], Iterator[Parsed]]) -> SettingsReader:
    def read(found: str, text: str) -> Iterator[Fact]:
        origin = Origin(path=found)
        for written, pattern, syntax in entries(text):
            yield IgnoreEntry(origin=origin, written=written, pattern=pattern, syntax=syntax)

    return SettingsReader(name=f"{path} entries", files=(path,), read=read)


IGNORE_FILES = {
    ".gitignore": _git_entries,
    ".hgignore": _mercurial_entries,
    ".bzrignore": _bazaar_entries,
    ".fossil-settings/ignore-glob": _fossil_entries,
}
IGNORE_READERS = tuple(_reader(path, entries) for path, entries in IGNORE_FILES.items())

__all__ = ["IGNORE_FILES", "IGNORE_READERS"]
