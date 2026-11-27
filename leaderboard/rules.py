"""Whether an entry may join the leaderboard: what a pull request that adds one is checked for before its preview.

An entry names a public, unarchived GitHub repository under an OSI-approved licence, no larger than `MOST_KB`, on a
board the validator knows (an ecosystem label), with its maintainers' consent, and is not listed twice. What GitHub
says about the repository is passed in (`Repository`), so the rules are checked offline in the tests and against
the GitHub API in CI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from leaderboard import _NAME, KINDS, Entry
from project_validator.ecosystems import BUILT_IN

MOST_KB = 2_000_000  # GitHub's `size`, in KiB: the whole history; a shallow clone is much smaller
# The OSI-approved licences GitHub detects, by SPDX identifier.
OSI_APPROVED = frozenset(
    {
        *("0BSD", "AFL-3.0", "AGPL-3.0", "Apache-2.0", "Artistic-2.0", "BSD-2-Clause", "BSD-3-Clause"),
        *("BSD-3-Clause-Clear", "BSL-1.0", "CECILL-2.1", "ECL-2.0", "EPL-1.0", "EPL-2.0", "EUPL-1.1", "EUPL-1.2"),
        *("GPL-2.0", "GPL-3.0", "ISC", "LGPL-2.1", "LGPL-3.0", "LPPL-1.3c", "MIT", "MIT-0", "MPL-2.0", "MS-PL"),
        *("MS-RL", "MulanPSL-2.0", "NCSA", "OFL-1.1", "OSL-3.0", "PostgreSQL", "UPL-1.0", "Unlicense", "Zlib"),
    }
)
BOARDS = frozenset(ecosystem.label for ecosystem in BUILT_IN)


@dataclass(frozen=True, slots=True, kw_only=True)
class Repository:
    """What GitHub says about a repository; `found` is False when it is not there (or not public)."""

    found: bool
    private: bool = False
    archived: bool = False
    license: str | None = None  # the SPDX identifier GitHub detected; NOASSERTION when it could not tell
    size_kb: int = 0


def problems(entry: Entry, repository: Repository) -> list[str]:
    """What keeps `entry` off the leaderboard, given what GitHub says about its repository; none when it may join."""
    found: list[str] = []
    if not _NAME.match(entry.name):
        found.append(f"`{entry.name}` is not a GitHub owner/repo")
    if entry.language not in BOARDS:
        found.append(f"`{entry.language}` is not a board: use an ecosystem label of the support matrix")
    if entry.kind not in KINDS:
        found.append(f"`{entry.kind}` is not a kind: {', '.join(KINDS[:-1])} or {KINDS[-1]}")
    if not (entry.seed or entry.consent.startswith("https://")):
        found.append("`consent` must link to the maintainers' approval (an issue, a comment or a pull request)")
    if not repository.found or repository.private:
        found.append(f"{entry.url} is not a public repository")
        return found
    if repository.archived:
        found.append(f"{entry.url} is archived")
    licence = entry.license or repository.license
    if licence not in OSI_APPROVED:
        found.append(
            f"its licence ({licence or 'none'}) is not one GitHub recognises as OSI-approved; when GitHub can not "
            "tell, name it with `license` and link to it"
        )
    if repository.size_kb > MOST_KB:
        found.append(f"it is {repository.size_kb // 1000} MB, more than the {MOST_KB // 1000} MB limit")
    return found


def duplicates(listed: Iterable[Entry]) -> list[str]:
    """The names listed more than once (GitHub names are not case sensitive)."""
    seen: dict[str, int] = {}
    for entry in listed:
        seen[entry.name.lower()] = seen.get(entry.name.lower(), 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


def changed(base: Sequence[Entry], head: Sequence[Entry]) -> list[Entry]:
    """The entries `head` adds or changes against `base`."""
    before = {entry.name: entry for entry in base}
    return [entry for entry in head if before.get(entry.name) != entry]


def github_repository(name: str, token: str | None = None) -> Repository:  # pragma: no cover - network
    """What the GitHub API says about `name`."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{name}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "project_validator-leaderboard"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return Repository(found=False)
        raise
    licence = data.get("license") or {}
    return Repository(
        found=True,
        private=bool(data.get("private")),
        archived=bool(data.get("archived")),
        license=licence.get("spdx_id"),
        size_kb=int(data.get("size", 0)),
    )


def token() -> str | None:  # pragma: no cover - environment
    return os.environ.get("GITHUB_TOKEN") or None
