"""Which CI configurations of the project are defunct: left from a CI it no longer runs on.

A dead configuration misleads its readers about what is tested, so it counts against the project
(`project_validator.checks.ci_current`). Two kinds of evidence say a provider's configuration is defunct:

- **certain:** the README shows the provider's badges only from a host that has shut down (travis-ci.org, whose
  projects that never moved to travis-ci.com stopped building in June 2021);
- **from the history:** the provider's configuration last changed more than `STALE_AFTER` before another provider's
  did, so the project kept working on its other CI and left this one behind. A provider whose configuration is the
  project's only CI is never judged by age. Without the git history (a shallow clone, a directory that is no
  checkout), the files' modification times stand in: a file is written no earlier than its last commit, in an
  unpacked copy that kept its times or a long-lived working copy. Times within `FRESH` of each other are those of a
  fresh checkout, which wrote every file at once, and tell nothing.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from project_validator.ci import CiFile, CiProvider
from project_validator.core import Project

# How far behind another provider's configuration one may fall before it looks left behind: two years.
STALE_AFTER = 2 * 365 * 24 * 60 * 60
_YEAR = 365.25 * 24 * 60 * 60
# How close together the files' modification times are when a checkout or an unpacked archive wrote them all: a day.
FRESH = 24 * 60 * 60


@dataclass(frozen=True, slots=True, kw_only=True)
class Defunct:
    """A provider whose configuration (`paths`) is defunct, and why: `certain` reasons, and what its `history` shows."""

    provider: str
    paths: tuple[str, ...]
    certain: tuple[str, ...] = ()
    history: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CiCurrency:
    """The defunct providers among the project's CI, and whether it has providers to compare whose ages neither the git
    history nor the file dates tell (`undated`)."""

    defunct: tuple[Defunct, ...]
    undated: bool


def ci_currency(project: Project, ci_files: Sequence[CiFile], readmes: Sequence[str]) -> CiCurrency:
    """Which providers of `ci_files` are defunct, from the badges `readmes` show and the history of the files."""
    providers = {ci_file.provider.name: ci_file.provider for ci_file in ci_files}
    paths = {name: tuple(f.path for f in ci_files if f.provider.name == name) for name in providers}
    known, dated = _dates(project, paths)
    found = []
    for name, provider in providers.items():
        certain = tuple(
            f"{paths[name][0]}: {readme}'s {name} badge is of {retired}"
            for readme in readmes
            if (retired := _retired_badge(provider, project.read_text(readme)))
        )
        history = _left_behind(name, paths[name][0], known, dated)
        if certain or history:
            found.append(Defunct(provider=name, paths=paths[name], certain=certain, history=history))
    return CiCurrency(defunct=tuple(found), undated=len(providers) > 1 and not known)


def _retired_badge(provider: CiProvider, readme: str) -> str | None:
    """What became of the host whose badge of `provider` the README shows, when it shows none from a live host."""
    if any(badge.regex.search(readme) for badge in provider.badges):
        return None
    return next((retired.name for retired in provider.retired_badges if retired.regex.search(readme)), None)


def _dates(project: Project, paths: dict[str, tuple[str, ...]]) -> tuple[dict[str, int], bool]:
    """When each provider's configuration last changed, by the git history, else by the files' modification times
    (`True` for those); none for a lone provider, which has no other to be compared with, or when the times are a
    fresh checkout's."""
    if len(paths) < 2:
        return {}, False
    changed = {name: _newest(project.last_changed(path) for path in found) for name, found in paths.items()}
    known = {name: when for name, when in changed.items() if when is not None}
    if known:
        return known, False
    files = [project.modified(path) for found in paths.values() for path in found]
    if not files or max(files) - min(files) <= FRESH:
        return {}, False
    return {name: max(project.modified(path) for path in found) for name, found in paths.items()}, True


def _newest(dates: Iterable[int | None]) -> int | None:
    """The latest of `dates`; None when none is known."""
    return max((when for when in dates if when is not None), default=None)


def _left_behind(name: str, path: str, changed: dict[str, int], dated: bool) -> tuple[str, ...]:
    """Why provider `name` (its configuration at `path`) looks left behind: the provider whose configuration changed
    most recently, when that was more than `STALE_AFTER` after this one's last change (by the file dates if `dated`)."""
    own = changed.get(name)
    others = [(when, other) for other, when in changed.items() if other != name]
    if own is None or not others:
        return ()
    newest, other = max(others)
    if newest - own <= STALE_AFTER:
        return ()
    years = int((newest - own) / _YEAR)
    when = f"last modified {_day(own)} (its file date)" if dated else f"last changed {_day(own)}"
    return (f"{path}: {when}, {years} years before {other} ({_day(newest)})",)


def _day(seconds: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(seconds))


__all__ = ["FRESH", "STALE_AFTER", "CiCurrency", "Defunct", "ci_currency"]
