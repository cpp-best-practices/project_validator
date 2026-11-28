"""Host: what the source-control host says of the repository beyond its settings (`host_details`, upstream #412): its
metadata, activity, security alerts, latest release and default-branch CI. Read online, with the host's token; what
was not read is said, and offline (or without a token) the Host line says why, so nothing is shown here."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from project_validator.about.detail import Detail
from project_validator.facts import Fact, Facts, as_dict
from project_validator.host_details import (
    PAGE,
    SECURITY_ITEMS,
    HostActivity,
    HostCi,
    HostRelease,
    HostRepository,
    HostSecurity,
    HostUnread,
)
from project_validator.words import counted

GROUP = "Host"


def _data(fact: Fact) -> dict[str, object]:
    return {key: value for key, value in as_dict(fact).items() if key not in ("kind", "origin")}


def _repository(found: HostRepository) -> str:
    words = [
        found.visibility,
        "archived" if found.archived else "not archived",
        "a fork" if found.fork else "not a fork",
    ]
    said = [", ".join(words), f"topics {', '.join(found.topics)}" if found.topics else "no topics"]
    said.append(f"homepage {found.homepage}" if found.homepage else "no homepage")
    said.append(
        f"{found.host} detects the {found.licence} licence" if found.licence else f"{found.host} detects no licence"
    )
    return f"{found.host} {found.repository}: {'; '.join(said)}"


def _ended(count: int, noun: str, verb: str, days: float | None) -> str:
    """`6 issues closed in a median of 5.6 days`; a full page is `at least 100 issues closed…`."""
    if not count:
        return f"no {noun}s {verb}"
    least = "at least " if count >= PAGE else ""
    return f"{least}{counted(count, noun)} {verb} in a median of {days} days"


def _activity(found: HostActivity) -> str:
    stale = f"{found.stale_pull_requests} stale" if found.stale_pull_requests else "none stale"
    opened = (
        f"{counted(found.open_issues, 'open issue')} and {counted(found.open_pull_requests, 'open pull request')}, "
        f"{stale} (not updated in {found.stale_days} days)"
    )
    closed = _ended(found.issues_closed, "issue", "closed", found.days_to_close)
    merged = _ended(found.pull_requests_merged, "pull request", "merged", found.days_to_merge)
    return f"{opened}; in the last {found.window_days} days, {closed} and {merged}"


def _alerts(count: int | None, noun: str, unread: dict[str, str]) -> str:
    if count is None:
        return f"{noun}s not read: {unread.get(f'{noun}s', 'not said')}"
    if count >= PAGE:
        return f"{PAGE} or more open {noun}s"
    return counted(count, f"open {noun}")


def _security(found: HostSecurity, unread: dict[str, str]) -> str:
    said = [
        _alerts(found.dependabot, "Dependabot alert", unread),
        _alerts(found.code_scanning, "code scanning alert", unread),
    ]
    if found.private_reporting is None:
        said.append(f"private vulnerability reporting not read: {unread.get('private vulnerability reporting')}")
    else:
        said.append(f"private vulnerability reporting {'on' if found.private_reporting else 'off'}")
    return "; ".join(said)


def _release(found: HostRelease) -> str:
    return f"latest release {found.tag}, of {found.date}" if found.tag else "no releases on GitHub"


def _duration(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def _ci(found: HostCi) -> str:
    result = found.state.lower() if found.state else "no result yet"
    ran = [f"{count} {conclusion.lower()}" for conclusion, count in found.suites.items()]
    ran += [f"{found.running} running"] if found.running else []
    total = sum(found.suites.values()) + found.running
    suites = f"{counted(total, 'check suite')} ({', '.join(ran)})" if total else "no check suites"
    over = f", the longest {_duration(found.seconds)}" if found.seconds is not None else ""
    return f"{found.branch} at {found.commit} ({found.date}): {result}; {suites}{over}"


def _shown[F: Fact](facts: Facts, kind: type[F], subject: str, say: Callable[[F], str]) -> Iterator[Detail]:
    for found in facts.of(kind):
        yield Detail(group=GROUP, subject=subject, text=say(found), data=_data(found))


def host(facts: Facts) -> Iterator[Detail]:
    """The host's details, each item in words, or why it was not read."""
    unread = {fact.item: fact.reason for fact in facts.of(HostUnread)}
    yield from _shown(facts, HostRepository, "the repository", _repository)
    yield from _shown(facts, HostActivity, "activity", _activity)
    yield from _shown(facts, HostSecurity, "security", lambda found: _security(found, unread))
    yield from _shown(facts, HostRelease, "releases", _release)
    yield from _shown(facts, HostCi, "default-branch CI", _ci)
    # The items not read at all (the security alerts are said with the security item).
    for item, reason in unread.items():
        if item not in SECURITY_ITEMS:
            yield Detail(group=GROUP, subject=item, text=f"not read: {reason}", data={"unread": reason})


__all__ = ["host"]
