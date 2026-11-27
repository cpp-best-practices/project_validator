"""The leaderboard: an opt-in list of open-source projects, scored every night (upstream #295) and published to GitHub
Pages, one board per language.

`projects.toml` lists each project: its GitHub `owner/repo`, the board it appears on (`language`, an ecosystem label
of the support matrix), its `kind` (a library, an application or a tool: projects are ranked against their kind and
their size too), and its maintainers' `consent` (a link to their approval, or `"seed"` for the seed list until
a maintainer confirms). It may name a `branch` (else the default branch), `auxiliary` and `exclude` (as the CLI
takes them) and a `license` when GitHub can not tell which it is. Unlike the corpus, entries are not pinned: each
night evaluates the branch as it is, so the board follows the projects.

- `leaderboard.evaluation` fetches a project and scores it;
- `leaderboard.history` keeps the nightly results and says what changed;
- `leaderboard.site` renders the boards, the project pages and the badges;
- `leaderboard.rules` checks a new entry (the pull request preview).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "projects.toml"
SEED = "seed"
# What a project is, as its entry declares: projects are ranked against those of their kind.
KINDS = ("library", "application", "tool")
_NAME = re.compile(r"^[\w.-]+/[\w.-]+$")


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    """A project on the leaderboard."""

    name: str
    language: str
    consent: str
    kind: str = "library"
    branch: str | None = None
    auxiliary: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    license: str | None = None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.name}"

    @property
    def slug(self) -> str:
        return self.name.replace("/", "--")

    @property
    def seed(self) -> bool:
        return self.consent == SEED


_FIELDS = frozenset(Entry.__dataclass_fields__)


class ManifestError(ValueError):
    pass


def _entry(listed: dict[str, object]) -> Entry:
    unknown = sorted(set(listed) - _FIELDS)
    if unknown:
        raise ManifestError(f"{listed.get('name', '?')}: unknown field(s) {', '.join(unknown)}")
    try:
        return Entry(
            name=str(listed["name"]),
            language=str(listed["language"]),
            kind=str(listed["kind"]),
            consent=str(listed["consent"]),
            branch=str(listed["branch"]) if "branch" in listed else None,
            auxiliary=tuple(str(item) for item in _list(listed.get("auxiliary", []))),
            exclude=tuple(str(item) for item in _list(listed.get("exclude", []))),
            license=str(listed["license"]) if "license" in listed else None,
        )
    except KeyError as missing:
        raise ManifestError(f"{listed.get('name', '?')}: missing {missing.args[0]}") from None


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"expected a list, not {value!r}")
    return value


def parse(text: str) -> list[Entry]:
    """The entries a manifest's text lists."""
    try:
        listed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(f"projects.toml does not parse: {error}") from None
    return [_entry(entry) for entry in listed.get("project", [])]


def entries(manifest: Path = MANIFEST) -> list[Entry]:
    """The leaderboard, as `projects.toml` lists it."""
    return parse(manifest.read_text(encoding="utf-8"))


def by_name(names: Iterable[str], listed: Iterable[Entry]) -> list[Entry]:
    """The listed entries `names` select; every name must be listed."""
    wanted = set(names)
    selected = [entry for entry in listed if entry.name in wanted]
    if missing := wanted - {entry.name for entry in selected}:
        raise KeyError(f"not on the leaderboard: {', '.join(sorted(missing))}")
    return selected
