"""The project's documents, read as `ProjectDocument` facts: its changelog (with the latest version an entry names),
CONTRIBUTING, CODEOWNERS, issue and pull request templates, and Doxygen's configuration (upstream #412)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import PurePosixPath

from project_validator.facts import Fact, Origin
from project_validator.facts.documents import (
    CHANGELOG,
    CODEOWNERS,
    CONTRIBUTING,
    DOXYGEN,
    ISSUE_TEMPLATE,
    PULL_REQUEST_TEMPLATE,
    ProjectDocument,
)
from project_validator.facts.settings import SettingsReader

# A changelog entry's heading that names a version: Markdown's `## [1.2.0] - 2026-01-01`, `# v1.2.0`, or
# reStructuredText's `1.2.0 (2026-01-01)` above its underline.
_MARKDOWN_ENTRY = re.compile(r"^#{1,6}\s*\[?v?(?P<version>\d+\.\d+(?:\.\d+)?[\w.+-]*)", re.MULTILINE)
_RST_ENTRY = re.compile(r"^v?(?P<version>\d+\.\d+(?:\.\d+)?[\w.+-]*)[^\n]*\n[=~^-]{3,}\s*$", re.MULTILINE)


def _latest(text: str) -> str:
    """The version the first entry that names one is of; "" when none does."""
    found = [match for pattern in (_MARKDOWN_ENTRY, _RST_ENTRY) if (match := pattern.search(text))]
    return min(found, key=lambda match: match.start())["version"] if found else ""


def _document(kind: str, *, latest: Callable[[str], str] | None = None) -> Callable[[str, str], Iterator[Fact]]:
    def read(path: str, text: str) -> Iterator[Fact]:
        if PurePosixPath(path).name.lower() == "config.yml":  # an issue chooser's settings, no template
            return
        yield ProjectDocument(origin=Origin(path=path), kind=kind, latest=latest(text) if latest else "")

    return read


def _cases(*names: str) -> tuple[str, ...]:
    """Each name as written, in upper, lower and title case."""
    return tuple(dict.fromkeys(form for name in names for form in (name, name.upper(), name.lower(), name.title())))


CHANGELOGS = SettingsReader(
    name="changelog",
    files=(*_cases("CHANGELOG*", "CHANGES*", "NEWS*"), "HISTORY.md", "HISTORY.rst"),
    read=_document(CHANGELOG, latest=_latest),
)
CONTRIBUTING_GUIDES = SettingsReader(name="CONTRIBUTING", files=_cases("CONTRIBUTING*"), read=_document(CONTRIBUTING))
CODE_OWNERS = SettingsReader(name="CODEOWNERS", files=("CODEOWNERS",), read=_document(CODEOWNERS))
ISSUE_TEMPLATES = SettingsReader(
    name="issue templates",
    files=(".github/ISSUE_TEMPLATE/*", *_cases("ISSUE_TEMPLATE.md")),
    read=_document(ISSUE_TEMPLATE),
)
PULL_REQUEST_TEMPLATES = SettingsReader(
    name="pull request templates",
    files=(*_cases("PULL_REQUEST_TEMPLATE*"), ".github/PULL_REQUEST_TEMPLATE/*"),
    read=_document(PULL_REQUEST_TEMPLATE),
)
DOXYFILES = SettingsReader(name="Doxygen", files=("Doxyfile*",), read=_document(DOXYGEN))

__all__ = [
    "CHANGELOGS",
    "CODE_OWNERS",
    "CONTRIBUTING_GUIDES",
    "DOXYFILES",
    "ISSUE_TEMPLATES",
    "PULL_REQUEST_TEMPLATES",
]
