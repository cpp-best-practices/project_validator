"""What the views share: how a result's places are named, how the checks are grouped, what was detected, in words.

Everything here is plain data and text, so that every view says the same thing and the tests can read it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.analysis import Analysis, Git, RoleSummary
from project_validator.core import Placed, Status
from project_validator.explanations import CATEGORIES, category
from project_validator.runner import Report

# How each status is shown, in words and as a symbol, worst first.
STATUS_ORDER = (Status.ERROR, Status.FAIL, Status.WARN, Status.PASS, Status.SKIP)
SYMBOLS = {Status.PASS: "✔", Status.WARN: "▲", Status.FAIL: "✘", Status.ERROR: "!", Status.SKIP: "-"}
OUTCOMES = {
    Status.PASS: "passed",
    Status.WARN: "warned",
    Status.FAIL: "failed",
    Status.ERROR: "errored",
    Status.SKIP: "skipped",
}
ROLE_NAMES = {
    "product": "the product",
    "test": "tests",
    "example": "examples",
    "docs": "documentation",
    "tooling": "tooling",
    "benchmark": "benchmarks",
    "template": "templates",
    "vendored": "vendored code",
}


def branch_label(git: Git) -> str:
    """The branch a checkout is on, or "detached"."""
    return git.branch if git.branch not in (None, "HEAD") else "detached"


def credit(value: float) -> str:
    """Extra credit, in percent, as the views show it: a tenth below one point, whole points above."""
    return f"{value:.1f}" if value < 1 else str(math.floor(round(value, 6)))


def dedupe(lines: Iterable[str]) -> list[str]:
    """`lines` without repeats, in order."""
    return list(dict.fromkeys(lines))


def place_label(place: Placed) -> str:
    """`C++`, `C++ in lib`, `Python (auxiliary: tooling)`; "" for the whole project."""
    unit = "" if place.unit in ("", ".") else f" in {place.unit}"
    auxiliary = f" (auxiliary: {', '.join(place.auxiliary)})" if place.auxiliary else ""
    return f"{place.ecosystem}{unit}{auxiliary}"


def judged_places(report: Report) -> list[Placed]:
    """The places a report judged (not skipped), worst first."""
    places = [place for place in report.result.places if place.result.status is not Status.SKIP]
    return sorted(places, key=lambda place: STATUS_ORDER.index(place.result.status))


def is_skipped(report: Report) -> bool:
    return report.result.status is Status.SKIP


@dataclass(frozen=True, slots=True)
class Group:
    category: str
    reports: tuple[Report, ...]

    @property
    def counts(self) -> Counter[Status]:
        return Counter(report.result.status for report in self.reports)


def grouped(reports: Sequence[Report]) -> list[Group]:
    """The judged reports by category, in the categories' order, worst first within each."""
    order = (*CATEGORIES, "Other")
    by_category: dict[str, list[Report]] = {}
    for report in reports:
        if not is_skipped(report):
            by_category.setdefault(category(report.check.name), []).append(report)
    return [
        Group(name, tuple(sorted(by_category[name], key=lambda r: (STATUS_ORDER.index(r.result.status), r.check.name))))
        for name in order
        if name in by_category
    ]


def counts(reports: Iterable[Report]) -> Counter[Status]:
    return Counter(report.result.status for report in reports)


def summary(reports: Sequence[Report]) -> str:
    """`49 checks: 30 passed, 8 warned, 3 failed, 8 skipped`."""
    found = counts(reports)
    outcomes = ", ".join(f"{found[status]} {OUTCOMES[status]}" for status in OUTCOMES if found[status])
    return f"{len(reports)} checks: {outcomes}" if reports else "no checks were run"


def ecosystems(analysis: Analysis) -> list[tuple[str, str]]:
    """(ecosystem, what recognised it) for each ecosystem detected."""
    if analysis.structure is None:
        return []
    return [(label, ", ".join(signals)) for label, signals in analysis.structure.recognised_by.items()]


def units(analysis: Analysis) -> list[tuple[str, str, str, str]]:
    """(directory, role, build systems, languages and formats) for each unit."""
    if analysis.structure is None:
        return []
    return [
        (
            unit.directory,
            unit.role,
            ", ".join(unit.build_systems) or "none",
            ", ".join(sorted(unit.languages | unit.formats)) or "-",
        )
        for unit in analysis.structure.units
    ]


def role_line(summary_: RoleSummary) -> str:
    """`tests: tests/ (12 files, C++, Python)`, with how it is judged."""
    directories = ", ".join(f"{directory}/" if directory != "." else "the root" for directory in summary_.directories)
    languages = f", {', '.join(summary_.languages)}" if summary_.languages else ""
    files = f"{summary_.files} file{'s' if summary_.files != 1 else ''}"
    return f"{ROLE_NAMES.get(summary_.role, summary_.role)}: {directories} ({files}{languages})"


def role_judgement(summary_: RoleSummary) -> str:
    """How the code in a role is judged, and how to change it."""
    if summary_.role == "vendored":
        return "other projects' code: never judged"
    if summary_.auxiliary:
        return "judged as auxiliary code (--auxiliary)"
    if summary_.suggestion:
        return f"judged as the product; {summary_.suggestion} would judge it as auxiliary"
    return "judged as the product"


def ci_summary(analysis: Analysis) -> str:
    """`GitHub Actions, GitLab CI: 33 jobs in 6 files`, or that there is none."""
    structure = analysis.structure
    if structure is None or not structure.ci_files:
        return "none found"
    jobs = len(structure.ci_jobs)
    files = len(structure.ci_files)
    providers = ", ".join(structure.ci_providers)
    return f"{providers}: {jobs} job{'s' if jobs != 1 else ''} in {files} file{'s' if files != 1 else ''}"


def reading(analysis: Analysis) -> str:
    """`1,500 facts in 0.31 s`: how much was read."""
    return f"{len(analysis.facts.all):,} facts in {analysis.seconds:.2f} s"


def unrecognised(analysis: Analysis) -> str:
    """The suffixes no ecosystem recognised, most common first: languages the validator does not know yet."""
    if analysis.structure is None or not analysis.structure.unrecognised_suffixes:
        return ""
    return ", ".join(f"{suffix} ({count})" for suffix, count in analysis.structure.unrecognised_suffixes[:8])


def short_path(path: str) -> str:
    return PurePosixPath(path).name or path


def fact_kinds(analysis: Analysis) -> list[tuple[str, int]]:
    """Each kind of fact found, with how many, most first."""
    found = Counter(type(fact).__name__ for fact in analysis.facts.all)
    return sorted(found.items(), key=lambda item: (-item[1], item[0]))


def iter_details(report: Report) -> Iterator[str]:
    yield from dedupe(report.result.details)


__all__ = [
    "OUTCOMES",
    "ROLE_NAMES",
    "STATUS_ORDER",
    "SYMBOLS",
    "Group",
    "branch_label",
    "ci_summary",
    "counts",
    "credit",
    "dedupe",
    "ecosystems",
    "fact_kinds",
    "grouped",
    "is_skipped",
    "judged_places",
    "place_label",
    "reading",
    "role_judgement",
    "role_line",
    "summary",
    "units",
    "unrecognised",
]
