"""What outside services say of the project (upstream #412): the OpenSSF Scorecard score of the repository the
`origin` remote names, and the latest version each package registry publishes of the packages the top manifests name
(PyPI, crates.io, npm: `policy/online.toml`), beside the version the manifest says. Shown in "About the project",
never judged.

Asked only with `--ask-services`, and never offline (`--offline`, `PROJECT_VALIDATOR_OFFLINE`): each is a call to a
service the project did not choose, so it is the user's to ask for. No token is sent. One call to Scorecard, and one
per package and registry; what a service could not say is a `ServiceUnread`, never a guess.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from project_validator import hosting, policy_tables
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.history import PackageName, PackageVersion, top_manifests
from project_validator.facts.roles import role
from project_validator.hosting import Refused

SCORECARD = "OpenSSF Scorecard"
_HEADERS = {
    "Accept": "application/json",
    # crates.io refuses a request that does not say who makes it.
    "User-Agent": "project_validator (https://github.com/cpp-best-practices/project_validator)",
}
_ORIGIN = Origin(path=".git/config")


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceAccess(Fact):
    """Why the outside services were not asked, though --ask-services was given (offline)."""

    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceUnread(Fact):
    """What a `service` could not say of a `subject` (the repository, a package), and why."""

    service: str
    subject: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Scorecard(Fact):
    """The OpenSSF Scorecard score of the `repository` (`github.com/o/r`), out of 10, and the day it was scored."""

    repository: str
    score: float
    date: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishedVersion(Fact):
    """The latest version a `registry` publishes of a `package` (None: it has no such package), beside the version
    its `manifest` says (None: it says none, as a pyproject.toml whose version is `dynamic`)."""

    registry: str
    package: str
    manifest: str
    version: str | None
    published: str | None


def _table() -> Mapping[str, Any]:
    return policy_tables.load("online")


def _refused(error: Refused) -> str:
    return f"{error.detail}, {error}" if error.detail else str(error)


def _scorecard(url: str | None) -> Fact:
    remote = hosting.remote_of(url or "")
    table = _table()["scorecard"]
    if remote is None:
        reason = "the project has no origin remote on a host"
        return ServiceUnread(origin=_ORIGIN, service=SCORECARD, subject="the repository", reason=reason)
    repository = f"{remote.host}/{remote.path}"
    if remote.host not in table["hosts"]:
        reason = f"Scorecard does not score {remote.host}"
        return ServiceUnread(origin=_ORIGIN, service=SCORECARD, subject=repository, reason=reason)
    try:
        answer = hosting.fetch(table["url"].format(host=remote.host, repository=remote.path), _HEADERS)
    except Refused as error:
        reason = f"Scorecard has no score for {repository} ({_refused(error)})"
        return ServiceUnread(origin=_ORIGIN, service=SCORECARD, subject=repository, reason=reason)
    found = answer if isinstance(answer, dict) else {}
    return Scorecard(
        origin=_ORIGIN, repository=repository, score=float(found.get("score") or 0), date=str(found.get("date"))[:10]
    )


def _at(answer: object, keys: list[str]) -> str | None:
    """The string `answer` holds at `keys`, if any."""
    for key in keys:
        answer = answer.get(key) if isinstance(answer, dict) else None
    return answer if isinstance(answer, str) else None


def _published(registry: Mapping[str, Any], package: PackageName, version: str | None) -> Fact:
    manifest = package.origin.path
    url = registry["url"].format(package=urllib.parse.quote(package.name, safe="@/"))
    try:
        published = _at(hosting.fetch(url, _HEADERS), registry["version"])
    except Refused as error:
        if error.status != 404:
            reason = f"{registry['name']} did not answer ({error})"
            return ServiceUnread(origin=_ORIGIN, service=registry["name"], subject=package.name, reason=reason)
        published = None
    return PublishedVersion(
        origin=Origin(path=manifest),
        registry=registry["name"],
        package=package.name,
        manifest=manifest,
        version=version,
        published=published,
    )


def _packages(facts: Facts) -> Iterator[Fact]:
    """What each registry publishes of the package each top manifest of the product names: a monorepo's packages
    below it are not asked of, so that a run makes few calls."""
    registries = {registry["manifest"]: registry for registry in _table()["registries"]}
    versions = {version.origin.path: version.version for version in facts.of(PackageVersion)}
    for package in top_manifests(name for name in facts.of(PackageName) if role(name.origin.path) == "product"):
        if (registry := registries.get(PurePosixPath(package.origin.path).name)) is not None:
            yield _published(registry, package, versions.get(package.origin.path))


def service_facts(url: str | None, facts: Facts, *, ask: bool, requested_offline: bool = False) -> Iterator[Fact]:
    """What the outside services say of the project whose `origin` remote is at `url`, when `ask`ed: nothing when not,
    and why not when offline."""
    if not ask:
        return
    if hosting.offline(requested_offline):
        yield ServiceAccess(origin=_ORIGIN, reason="outside services are not asked offline (--offline)")
        return
    yield _scorecard(url)
    yield from _packages(facts)


__all__ = ["SCORECARD", "PublishedVersion", "Scorecard", "ServiceAccess", "ServiceUnread", "service_facts"]
