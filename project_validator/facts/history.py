"""The repository's history and releases (upstream #412), read from the checkout's git: how old it is, how many
commits the year before its last commit holds and by how many authors, how many of them are signed, its tags, and the
version its manifests say it is. Shown, never judged.

Every window is counted back from the last commit, not from today, so the same checkout always says the same thing.
A shallow clone holds only part of its history: its age and authors are not known, and are not guessed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from project_validator.core import Project
from project_validator.facts import Fact, Origin
from project_validator.facts.settings import SettingsReader
from project_validator.facts.versions import Declares

_ORIGIN = Origin(path=".", at=("git",))
# The window a project's recent activity is counted in, back from its last commit.
YEAR = timedelta(days=365)


@dataclass(frozen=True, slots=True, kw_only=True)
class History(Fact):
    """The checkout's history: its commits (those a shallow clone holds), the dates of its first commit ("" in a
    shallow clone) and its last, and, of the commits in the year before the last, how many there are, by how many
    authors, the most active author's share, and how many carry a signature."""

    shallow: bool
    commits: int
    first: str
    last: str
    recent: int
    authors: int
    top_share: float
    signed: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Tag(Fact):
    """A tag of the checkout, and the date it was made (an annotated tag's, else its commit's)."""

    name: str
    date: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageVersion(Fact):
    """The version a manifest says the package is (`version = "1.3.0"` in Cargo.toml)."""

    version: str


def package_version_reader(*, name: str, files: tuple[str, ...], declares: Declares) -> SettingsReader:
    """A reader of the manifests `files`, whose package version `declares` reads; one that does not parse says none."""

    def read(path: str, text: str) -> Iterator[Fact]:
        try:
            found = [version for version, _pinned in declares(text)]
        except ValueError:  # TOML and JSON errors are ValueErrors
            return
        yield from (PackageVersion(origin=Origin(path=path), version=version) for version in found if version)

    return SettingsReader(name=name, files=files, read=read)


def _recent(project: Project, since: str) -> tuple[int, Counter[str], int]:
    """The commits since `since`: how many, by author, and how many carry a signature (a `gpgsig` header: signed,
    whether or not the signature could be checked here)."""
    raw = project.git("log", f"--since={since}", "--pretty=raw", "HEAD") or ""
    authors: Counter[str] = Counter()
    commits = signed = 0
    for line in raw.splitlines():
        if line.startswith("commit "):
            commits += 1
        elif line.startswith("author ") and (found := re.search(r"<([^>]*)>", line)):
            authors[found[1].lower()] += 1
        elif line.startswith("gpgsig"):
            signed += 1
    return commits, authors, signed


def _tags(project: Project) -> Iterator[Tag]:
    listed = project.git("for-each-ref", "refs/tags", "--format=%(refname:short)%09%(creatordate:short)") or ""
    for line in listed.splitlines():
        name, _, date = line.partition("\t")
        if name:
            yield Tag(origin=Origin(path=".", at=("tags", name)), name=name, date=date)


def history_facts(project: Project) -> Iterator[Fact]:
    """The checkout's history and tags; nothing outside a checkout whose root the project is."""
    last = project.git("log", "-1", "--format=%cI", "HEAD")
    if not last:
        return
    shallow = project.shallow()
    since = (datetime.fromisoformat(last) - YEAR).isoformat()
    recent, authors, signed = _recent(project, since)
    roots = (project.git("log", "--max-parents=0", "--format=%cs", "HEAD") or "").split()
    yield History(
        origin=_ORIGIN,
        shallow=shallow,
        commits=int(project.git("rev-list", "--count", "HEAD") or 0),
        first="" if shallow else min(roots, default=""),
        last=last[:10],
        recent=recent,
        authors=len(authors),
        top_share=round(max(authors.values(), default=0) / recent, 4) if recent else 0.0,
        signed=signed,
    )
    yield from _tags(project)


__all__ = ["YEAR", "History", "PackageVersion", "Tag", "history_facts", "package_version_reader"]
