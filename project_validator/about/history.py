"""History and Releases: the repository's age, its last year's commits and authors, its signed commits, its tags and
how often they come, and the version its manifests say it is (upstream #412)."""

from __future__ import annotations

import itertools
import re
import statistics
from collections.abc import Iterator
from datetime import date

from project_validator.about.detail import Detail, in_product
from project_validator.facts import Facts
from project_validator.facts.history import YEAR, History, PackageVersion, Tag

# A tag that names a version: `v1.2.0`, `1.2`, `release-3.1.4`.
_VERSION_TAG = re.compile(r"(?:[a-z]+[-_/]?)?v?(?P<version>\d+(?:\.\d+)+)", re.IGNORECASE)


def _signed(found: History) -> str:
    if not found.signed:
        return "none signed"
    return f"{round(100 * found.signed / found.recent)}% of them signed"


def _history(found: History) -> Detail:
    if found.shallow:
        held = f"holding {found.commits:,} of its commits, the last on {found.last}"
        text = f"a shallow clone, {held}: its history is not read"
    else:
        authors = f"by {found.authors} {'author' if found.authors == 1 else 'authors'}"
        share = f" (the most active made {round(100 * found.top_share)}% of them)" if found.authors > 1 else ""
        text = (
            f"{found.commits:,} commits since {found.first}, the last on {found.last}; {found.recent:,} in the year "
            f"before it, {authors}{share}; {_signed(found)}"
        )
    data = {
        "shallow": found.shallow,
        "commits": found.commits,
        "first": found.first or None,
        "last": found.last,
        "recent": found.recent,
        "authors": found.authors,
        "top_share": found.top_share,
        "signed": found.signed,
    }
    return Detail(group="History", subject="the repository", text=text, data=data)


def _cadence(tags: list[Tag], last: str) -> tuple[int, int | None]:
    """How many version tags the year before the last commit holds, and the median days between them."""
    since = date.fromisoformat(last) - YEAR
    dates = sorted(date.fromisoformat(tag.date) for tag in tags if tag.date)
    recent = [found for found in dates if found >= since]
    gaps = [(later - earlier).days for earlier, later in itertools.pairwise(recent)]
    return len(recent), round(statistics.median(gaps)) if gaps else None


def _manifests(facts: Facts, latest: str | None) -> list[str]:
    """What the top manifests say the version is (those nearest the root: a monorepo's packages below them are
    counted), beside the latest version tag's."""
    versions = in_product(facts.of(PackageVersion))
    depth = min((version.origin.path.count("/") for version in versions), default=0)
    top = [version for version in versions if version.origin.path.count("/") == depth]
    words = []
    for version in top:
        said = f"{version.origin.path} says {version.version}"
        if latest is not None:
            said += ", the latest tag's" if version.version == latest else f", not the latest tag's {latest}"
        words.append(said)
    if rest := len({version.origin.path for version in versions}) - len({version.origin.path for version in top}):
        words.append(f"and {rest} more {'package' if rest == 1 else 'packages'}")
    return words


def _releases(facts: Facts, history: History) -> Detail | None:
    tags = [tag for tag in facts.of(Tag) if _VERSION_TAG.fullmatch(tag.name)]
    latest = max(tags, key=lambda tag: (tag.date, tag.name), default=None)
    version = match["version"] if latest and (match := _VERSION_TAG.fullmatch(latest.name)) else None
    words = []
    if latest is not None:
        count, gap = _cadence(tags, history.last)
        words.append(f"latest tag {latest.name}, of {latest.date}")
        words.append(
            f"{count} version tags in the year before the last commit"
            + (f", a median of {gap} days apart" if gap is not None else "")
        )
    elif not history.shallow:
        words.append("no version tags")
    words += _manifests(facts, version)
    if not words:
        return None
    data = {"latest": latest.name if latest else None, "date": latest.date if latest else None, "tags": len(tags)}
    return Detail(group="Releases", subject="the repository", text="; ".join(words), data=data)


def history(facts: Facts) -> Iterator[Detail]:
    """The repository's history, then its releases; nothing outside a checkout."""
    for found in facts.of(History):
        yield _history(found)
        if releases := _releases(facts, found):
            yield releases


__all__ = ["history"]
