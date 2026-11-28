"""Tools and CI: every tool CI runs, by what it does, and the shape of the CI: the events it runs on, whether pull
requests from forks run it, and how many jobs on how many OSes (upstream #412)."""

from __future__ import annotations

from collections.abc import Iterator

from project_validator.about.detail import Detail
from project_validator.facts import CiTriggers, Facts
from project_validator.facts.jobs import Job
from project_validator.facts.tools import ToolRun

# The aspects a tool run provides, in the order they are shown; any other follows, by name.
ASPECTS = (
    "format",
    "analysis",
    "type-check",
    "test",
    "coverage",
    "mutation",
    "fuzz",
    "security",
    "audit",
    "function-length",
)
# The events by which a pull request from a fork runs a GitHub workflow.
_PULL_REQUESTS = frozenset({"pull_request", "pull_request_target"})


def _order(aspect: str) -> tuple[int, str]:
    return (ASPECTS.index(aspect) if aspect in ASPECTS else len(ASPECTS), aspect)


def tools(facts: Facts) -> Iterator[Detail]:
    """The tools CI runs, by aspect: `format: ruff format; analysis: ruff check; test: pytest`."""
    by_aspect: dict[str, set[str]] = {}
    for run in facts.of(ToolRun):
        for aspect in run.provides:
            by_aspect.setdefault(aspect, set()).add(run.tool)
    if not by_aspect:
        return
    ordered = sorted(by_aspect, key=_order)
    text = "; ".join(f"{aspect}: {', '.join(sorted(by_aspect[aspect]))}" for aspect in ordered)
    data = {aspect: sorted(by_aspect[aspect]) for aspect in ordered}
    yield Detail(group="Tools", subject="CI", text=text, data=data)


def ci_shape(facts: Facts) -> Iterator[Detail]:
    """The events CI runs on, whether pull requests from forks run it, and its jobs and OSes."""
    events = sorted({event for triggers in facts.of(CiTriggers) for event in triggers.events})
    jobs = facts.of(Job)
    systems = sorted({job.os for job in jobs if job.os and job.os != "unknown"})
    words = []
    if events:
        words.append(f"runs on {', '.join(events)}")
        words.append(f"pull requests from forks {'run' if _PULL_REQUESTS & set(events) else 'do not run'} it")
    if jobs:
        oses = f" on {len(systems)} {'OS' if len(systems) == 1 else 'OSes'} ({', '.join(systems)})" if systems else ""
        words.append(f"{len(jobs)} {'job' if len(jobs) == 1 else 'jobs'}{oses}")
    if words:
        data = {"events": events, "forks": bool(_PULL_REQUESTS & set(events)) if events else None, "jobs": len(jobs)}
        yield Detail(group="CI", subject="the CI", text="; ".join(words), data={**data, "oses": systems})


__all__ = ["ASPECTS", "ci_shape", "tools"]
