"""Services: what outside services say of the project (`services`, upstream #412), asked only with --ask-services: the
OpenSSF Scorecard score, and the latest version each package registry publishes beside the manifest's."""

from __future__ import annotations

from collections.abc import Iterator

from project_validator.about.detail import Detail
from project_validator.facts import Facts
from project_validator.services import SCORECARD, PublishedVersion, Scorecard, ServiceAccess, ServiceUnread

GROUP = "Services"


def _published(found: PublishedVersion) -> str:
    said = f"{found.manifest} says {found.version}" if found.version else f"{found.manifest} says no version"
    if found.published is None:
        return f"not published on {found.registry} ({said})"
    if found.published == found.version:
        return f"{found.published} is published, the version {found.manifest} says"
    return f"{found.published} is published; {said}"


def outside_services(facts: Facts) -> Iterator[Detail]:
    """What each service said, or why it said nothing."""
    for access in facts.of(ServiceAccess):
        yield Detail(group=GROUP, subject="outside services", text=f"not read: {access.reason}")
    for score in facts.of(Scorecard):
        text = f"{score.repository} scores {score.score} of 10 (on {score.date})"
        data = {"repository": score.repository, "score": score.score, "date": score.date}
        yield Detail(group=GROUP, subject=SCORECARD, text=text, data=data)
    for version in facts.of(PublishedVersion):
        data = {"package": version.package, "version": version.version, "published": version.published}
        yield Detail(group=GROUP, subject=f"{version.registry} {version.package}", text=_published(version), data=data)
    for unread in facts.of(ServiceUnread):
        subject = unread.service if unread.service == SCORECARD else f"{unread.service} {unread.subject}"
        yield Detail(group=GROUP, subject=subject, text=f"not read: {unread.reason}", data={"unread": unread.reason})


__all__ = ["outside_services"]
