"""Tools and CI: every tool CI runs, by what it does and with the versions it is pinned at, and the shape of the CI:
the events it runs on, whether pull requests from forks run it, and how many jobs on how many OSes and architectures
(upstream #412)."""

from __future__ import annotations

from collections.abc import Iterator

from project_validator.about.detail import Detail
from project_validator.facts import CiJob, CiTriggers, Facts
from project_validator.facts.jobs import Job
from project_validator.facts.pins import normal, pins
from project_validator.facts.tools import ToolRun
from project_validator.words import counted

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


def _versioned(tool: str, pinned: dict[str, set[str]]) -> str:
    """A tool with the exact versions it is pinned at (`ruff check 0.6.9`): the versions of the package named like the
    tool (`ruff-format`) or like its program (`ruff`). A tool a bundle runs (`eslint's max-lines-per-function`) has
    the bundle's version, not its own, so none is said."""
    if "'s " in tool:
        return tool
    versions = pinned.get(normal(tool)) or pinned.get(normal(tool.split()[0])) or set()
    ordered = sorted(versions, key=lambda version: [int(part) if part.isdigit() else -1 for part in version.split(".")])
    return f"{tool} {' or '.join(ordered)}" if ordered else tool


def tools(facts: Facts) -> Iterator[Detail]:
    """The tools CI runs, by aspect: `format: ruff format; analysis: ruff check; test: pytest`."""
    by_aspect: dict[str, set[str]] = {}
    pinned = pins(facts)
    for run in facts.of(ToolRun):
        for aspect in run.provides:
            by_aspect.setdefault(aspect, set()).add(_versioned(run.tool, pinned))
    if not by_aspect:
        return
    ordered = sorted(by_aspect, key=_order)
    text = "; ".join(f"{aspect}: {', '.join(sorted(by_aspect[aspect]))}" for aspect in ordered)
    data = {aspect: sorted(by_aspect[aspect]) for aspect in ordered}
    yield Detail(group="Tools", subject="CI", text=text, data=data)


def _counted(names: list[str], noun: str, plural: str = "") -> str:
    """`2 architectures (arm64, x64)`."""
    return f"{len(names)} {noun if len(names) == 1 else plural or noun + 's'} ({', '.join(names)})"


def _jobs(facts: Facts) -> tuple[str, int, list[str], list[str]]:
    """`9 jobs on 3 OSes (linux, macos, windows) and 2 architectures (arm64, x64)`, with the jobs, OSes and
    architectures it counts."""
    jobs = facts.of(Job)
    systems = sorted({job.os for job in jobs if job.os and job.os != "unknown"})
    architectures = sorted({job.arch for job in facts.of(CiJob) if job.arch}) if systems else []
    words = counted(len(jobs), "job") if jobs else ""
    if jobs and systems:
        words += f" on {_counted(systems, 'OS', 'OSes')}"
        words += f" and {_counted(architectures, 'architecture')}" if architectures else ""
    return words, len(jobs), systems, architectures


def ci_shape(facts: Facts) -> Iterator[Detail]:
    """The events CI runs on, whether pull requests from forks run it, and its jobs, OSes and architectures."""
    events = sorted({event for triggers in facts.of(CiTriggers) for event in triggers.events})
    forks = bool(_PULL_REQUESTS & set(events))
    jobs, count, systems, architectures = _jobs(facts)
    words = [f"runs on {', '.join(events)}", f"pull requests from forks {'run' if forks else 'do not run'} it"]
    words = [*(words if events else []), *([jobs] if jobs else [])]
    if words:
        data = {"events": events, "forks": forks if events else None, "jobs": count}
        yield Detail(
            group="CI",
            subject="the CI",
            text="; ".join(words),
            data={**data, "oses": systems, "architectures": architectures},
        )


__all__ = ["ASPECTS", "ci_shape", "tools"]
