"""What the source-control host says of the repository beyond its settings (upstream #412): its metadata (archived, a
fork, visibility, topics, homepage, the licence the host detects), its activity (open issues and pull requests, the
stale ones, the median time to close and to merge), its open security alerts and private vulnerability reporting, its
latest release, and the result of CI on the default branch's latest commit. Shown in "About the project", never
judged.

It is read with the settings (`hosting.host_facts`), with the same token, and never offline. Of GitHub it takes four
calls beyond the settings' three, whose repository answer it shares: one GraphQL query (activity, release, CI) and three
REST calls (Dependabot alerts, code scanning alerts, private vulnerability reporting), which need access the token may
not have; what it cannot read is a `HostUnread` that says why, never a guess. The other hosts' details are not read.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from project_validator import policy_tables
from project_validator.facts import NOTHING, Fact, Origin
from project_validator.hosting import HOSTS, Ask, Details, Refused, Remote, github_api

# The most alerts one REST call lists: a page that is full holds at least that many.
PAGE = 100


@dataclass(frozen=True, slots=True, kw_only=True)
class HostUnread(Fact):
    """An `item` of the host's details that was not read, and why."""

    item: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class HostRepository(Fact):
    """What the host says the repository is: archived or not, a fork or not, its visibility, topics and homepage, and
    the licence the host detects (its SPDX id; None: none detected)."""

    host: str
    repository: str
    archived: bool
    fork: bool
    visibility: str
    topics: tuple[str, ...] = ()
    homepage: str | None = None
    licence: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HostActivity(Fact):
    """The open issues and pull requests, those not updated in `stale_days`; and, of the issues closed and the pull
    requests merged in the `window_days` before the run (at most a page of each), how many and the median days it
    took (None: none)."""

    open_issues: int
    open_pull_requests: int
    stale_pull_requests: int
    issues_closed: int
    days_to_close: float | None
    pull_requests_merged: int
    days_to_merge: float | None
    window_days: int
    stale_days: int


@dataclass(frozen=True, slots=True, kw_only=True)
class HostRelease(Fact):
    """The latest release on the host: its tag, name and date (None: no release)."""

    tag: str | None = None
    name: str | None = None
    date: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HostCi(Fact):
    """CI on the default branch's latest commit: the host's combined `state` of its checks (None: no result), the
    latest check suite of each workflow (or app) that ran on it, by conclusion, how many are still running, and the
    seconds the longest that ended took (None: none ended)."""

    branch: str
    commit: str
    date: str
    state: str | None
    suites: Mapping[str, int] = NOTHING
    running: int = 0
    seconds: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HostSecurity(Fact):
    """The open Dependabot and code scanning alerts (`PAGE`: that many or more; None: not read, see `HostUnread`), and
    whether private vulnerability reporting is on (None: not read)."""

    dependabot: int | None = None
    code_scanning: int | None = None
    private_reporting: bool | None = None


def _table() -> Mapping[str, int]:
    found: Mapping[str, int] = policy_tables.load("online")["activity"]
    return found


_QUERY = """
query($owner: String!, $name: String!, $stale: String!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN) { totalCount }
    pullRequests(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { createdAt closedAt }
    }
    mergedPullRequests: pullRequests(states: MERGED, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { createdAt mergedAt }
    }
    latestRelease { tagName name publishedAt }
    defaultBranchRef {
      name
      target {
        ... on Commit {
          oid committedDate statusCheckRollup { state }
          checkSuites(first: 100) {
            nodes { status conclusion createdAt updatedAt app { slug } workflowRun { workflow { name } } }
          }
        }
      }
    }
  }
  stale: search(query: $stale, type: ISSUE) { issueCount }
}
"""
_GRAPHQL_ITEMS = ("activity", "releases", "default-branch CI")
# The items `HostSecurity` says, read or not.
SECURITY_ITEMS = ("Dependabot alerts", "code scanning alerts", "private vulnerability reporting")


def _object(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _nodes(value: object) -> list[Mapping[str, object]]:
    nodes = _object(value).get("nodes")
    return [_object(node) for node in nodes] if isinstance(nodes, list) else []


def _count(value: object, key: str = "totalCount") -> int:
    found = _object(value).get(key)
    return found if isinstance(found, int) else 0


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _refused(error: Refused) -> str:
    return f"{error.detail} ({error})" if error.detail else str(error)


def _repository(remote: Remote, answer: object, origin: Origin) -> HostRepository:
    found = _object(answer)
    topics = found.get("topics")
    return HostRepository(
        origin=origin,
        host="GitHub",
        repository=remote.path,
        archived=bool(found.get("archived")),
        fork=bool(found.get("fork")),
        visibility=str(found.get("visibility") or ("private" if found.get("private") else "public")),
        topics=tuple(str(topic) for topic in topics) if isinstance(topics, list) else (),
        homepage=str(found["homepage"]) if found.get("homepage") else None,
        licence=str(_object(found.get("license")).get("spdx_id") or "") or None,
    )


def _graphql(remote: Remote, ask: Ask, now: datetime) -> Mapping[str, object] | str:
    """The repository's answer to the query (with the stale pull requests' search), or why there is none."""
    owner, _, name = remote.path.partition("/")
    since = (now - timedelta(days=_table()["stale_days"])).date().isoformat()
    variables = {"owner": owner, "name": name, "stale": f"repo:{remote.path} is:pr is:open updated:<{since}"}
    url = "https://api.github.com/graphql" if remote.host == "github.com" else f"https://{remote.host}/api/graphql"
    try:
        answer = _object(ask(url, {"query": _QUERY, "variables": variables}))
    except Refused as error:
        return f"GitHub did not answer ({_refused(error)})"
    data = _object(answer.get("data"))
    if not (repository := _object(data.get("repository"))):
        errors = answer.get("errors")
        said = "; ".join(str(_object(error).get("message")) for error in errors) if isinstance(errors, list) else ""
        return f"GitHub said: {said or 'nothing of the repository'}"
    return {**repository, "stale": data.get("stale")}


def _median_days(nodes: list[Mapping[str, object]], ended: str, since: datetime) -> tuple[int, float | None]:
    """How many of `nodes` ended (at their `ended` time) since `since`, and the median days they took."""
    spans = [
        (end - start).total_seconds() / 86400
        for node in nodes
        if (end := _when(node.get(ended))) is not None and end >= since and (start := _when(node.get("createdAt")))
    ]
    return len(spans), round(statistics.median(spans), 1) if spans else None


def _activity(repository: Mapping[str, object], now: datetime, origin: Origin) -> HostActivity:
    table = _table()
    since = now - timedelta(days=table["window_days"])
    closed, to_close = _median_days(_nodes(repository.get("closedIssues")), "closedAt", since)
    merged, to_merge = _median_days(_nodes(repository.get("mergedPullRequests")), "mergedAt", since)
    return HostActivity(
        origin=origin,
        open_issues=_count(repository.get("issues")),
        open_pull_requests=_count(repository.get("pullRequests")),
        stale_pull_requests=_count(repository.get("stale"), "issueCount"),
        issues_closed=closed,
        days_to_close=to_close,
        pull_requests_merged=merged,
        days_to_merge=to_merge,
        window_days=table["window_days"],
        stale_days=table["stale_days"],
    )


def _release(repository: Mapping[str, object], origin: Origin) -> HostRelease:
    latest = _object(repository.get("latestRelease"))
    if not latest:
        return HostRelease(origin=origin)
    published = str(latest.get("publishedAt") or "")
    return HostRelease(origin=origin, tag=str(latest.get("tagName")), name=str(latest.get("name")), date=published[:10])


def _ran(suite: Mapping[str, object]) -> bool:
    """A check suite that ran: a workflow run, or another app's suite that started (an app that has nothing to run
    leaves its suite queued)."""
    return suite.get("workflowRun") is not None or suite.get("status") != "QUEUED"


def _latest(suites: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """The latest suite of each workflow, or of each other app: a commit a schedule runs on daily has a suite a day."""
    latest: dict[str, Mapping[str, object]] = {}
    for suite in sorted(suites, key=lambda suite: str(suite.get("createdAt"))):
        workflow = _object(_object(suite.get("workflowRun")).get("workflow")).get("name")
        latest[f"workflow {workflow}" if workflow else f"app {_object(suite.get('app')).get('slug')}"] = suite
    return list(latest.values())


def _seconds(suite: Mapping[str, object]) -> int | None:
    start, end = _when(suite.get("createdAt")), _when(suite.get("updatedAt"))
    return round((end - start).total_seconds()) if start and end else None


def _ci(repository: Mapping[str, object], origin: Origin) -> HostCi | HostUnread:
    branch = _object(repository.get("defaultBranchRef"))
    commit = _object(branch.get("target"))
    if not commit:
        return HostUnread(origin=origin, item="default-branch CI", reason="the repository has no default branch")
    suites = _latest([suite for suite in _nodes(commit.get("checkSuites")) if _ran(suite)])
    ended = [suite for suite in suites if suite.get("status") == "COMPLETED"]
    took = [seconds for suite in ended if (seconds := _seconds(suite)) is not None]
    return HostCi(
        origin=origin,
        branch=str(branch.get("name")),
        commit=str(commit.get("oid"))[:7],
        date=str(commit.get("committedDate"))[:10],
        state=str(state) if (state := _object(commit.get("statusCheckRollup")).get("state")) else None,
        suites=dict(Counter(str(suite.get("conclusion")) for suite in ended)),
        running=len(suites) - len(ended),
        seconds=max(took, default=None),
    )


def _graphql_facts(remote: Remote, ask: Ask, origin: Origin, now: datetime) -> Iterator[Fact]:
    repository = _graphql(remote, ask, now)
    if isinstance(repository, str):
        yield from (HostUnread(origin=origin, item=item, reason=repository) for item in _GRAPHQL_ITEMS)
        return
    yield _activity(repository, now, origin)
    yield _release(repository, origin)
    yield _ci(repository, origin)


def _alerts(ask: Ask, url: str) -> int | str:
    """How many open alerts the first page at `url` lists, or why it was not read."""
    try:
        answer = ask(f"{url}?state=open&per_page={PAGE}")
    except Refused as error:
        needs = (
            "; it needs a token that may read the repository's security alerts" if error.status in (401, 403) else ""
        )
        return f"{error.detail or 'refused'} ({error}{needs})"
    return len(answer) if isinstance(answer, list) else 0


def _reporting(ask: Ask, url: str) -> bool | str:
    try:
        return bool(_object(ask(url)).get("enabled"))
    except Refused as error:
        return _refused(error)


def _read[T](value: T | str) -> T | None:
    """A value read, or None for the reason it was not."""
    return None if isinstance(value, str) else value


def _security(base: str, ask: Ask, origin: Origin) -> Iterator[Fact]:
    dependabot = _alerts(ask, f"{base}/dependabot/alerts")
    scanning = _alerts(ask, f"{base}/code-scanning/alerts")
    reporting = _reporting(ask, f"{base}/private-vulnerability-reporting")
    read = dict(zip(SECURITY_ITEMS, (dependabot, scanning, reporting), strict=True))
    yield from (HostUnread(origin=origin, item=item, reason=why) for item, why in read.items() if isinstance(why, str))
    yield HostSecurity(
        origin=origin, dependabot=_read(dependabot), code_scanning=_read(scanning), private_reporting=_read(reporting)
    )


def github_details(remote: Remote, ask: Ask, origin: Origin, *, now: datetime | None = None) -> Iterator[Fact]:
    """What GitHub says of the repository beyond its settings, its windows counted back from `now` (the run's)."""
    base = f"{github_api(remote)}/repos/{remote.path}"
    yield _repository(remote, ask(base), origin)
    yield from _graphql_facts(remote, ask, origin, now or datetime.now(UTC))
    yield from _security(base, ask, origin)


def _not_read(name: str, _remote: Remote, _ask: Ask, origin: Origin) -> Iterator[Fact]:
    yield HostUnread(origin=origin, item="the host's details", reason=f"{name}'s are not read: only GitHub's, for now")


# The reader of each host's details, by the host's name (`hosting.HOSTS`).
DETAILS: Mapping[str, Details] = {
    host.name: github_details if host.name == "GitHub" else partial(_not_read, host.name) for host in HOSTS
}

__all__ = [
    "DETAILS",
    "PAGE",
    "SECURITY_ITEMS",
    "HostActivity",
    "HostCi",
    "HostRelease",
    "HostRepository",
    "HostSecurity",
    "HostUnread",
    "github_details",
]
