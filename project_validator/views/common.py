"""What the views share: how a result's places are named, how the checks are grouped, what was detected, in words.

Everything here is plain data and text, so that every view says the same thing and the tests can read it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from project_validator.analysis import Analysis, Git, RoleSummary
from project_validator.core import Placed, Status
from project_validator.explanations import CATEGORIES, category
from project_validator.facts import PartlyRead
from project_validator.project_map import LanguageFiles, Place
from project_validator.runner import Report
from project_validator.words import counted, folder

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
    languages = f", {', '.join(summary_.languages)}" if summary_.languages else ""
    files = counted(summary_.files, "file")
    return f"{ROLE_NAMES.get(summary_.role, summary_.role)}: {role_directories(summary_)} ({files}{languages})"


def role_directories(summary_: RoleSummary) -> str:
    """`src/, tools/`: the top-level folders the code in a role is in."""
    return ", ".join(folder(directory) for directory in summary_.directories)


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
    return f"{providers}: {counted(jobs, 'job')} in {counted(files, 'file')}"


def reading(analysis: Analysis) -> str:
    """`1,500 facts in 0.31 s`: how much was read, how many paths git ignores were left out, and how many places a
    reader could follow only in part (see `partly_read`)."""
    found = [f"{len(analysis.facts.all):,} facts in {analysis.seconds:.2f} s"]
    if count := len(analysis.ignored):
        found.append(f"{counted(count, 'path')} git ignores left out")
    if count := len(partly_read(analysis)):
        found.append(f"{counted(count, 'place')} read only in part")
    return "; ".join(found)


def partly_read(analysis: Analysis) -> list[str]:
    """The places a reader could follow only in part, as `subject: reason (origin)`: noted, not judged."""
    return list(
        dict.fromkeys(f"{fact.subject}: {fact.reason} ({fact.origin})" for fact in analysis.facts.of(PartlyRead))
    )


PLACES_SHOWN = 4  # folders listed for a language before the rest are counted


def place_count(place: Place) -> str:
    """`(3)`, `(1, test)`: how many of a language's files a folder holds, and their role when not the product's."""
    return f"({place.files}{'' if place.role == 'product' else f', {place.role}'})"


def shown_places(found: LanguageFiles) -> tuple[tuple[Place, ...], str]:
    """The folders of a language listed, and what is said of the rest (` and 2 more folders (5 files)`, else "")."""
    shown, rest = found.places[:PLACES_SHOWN], found.places[PLACES_SHOWN:]
    if not rest:
        return shown, ""
    return shown, f" and {counted(len(rest), 'more folder')} ({counted(sum(place.files for place in rest), 'file')})"


def file_count(found: LanguageFiles) -> str:
    """`4 files (44%)`: how many files a language has, and its share of the project's own files."""
    share = "<1" if found.share < 0.01 else str(round(found.share * 100))
    return f"{counted(found.files, 'file')} ({share}%)"


def language_files(found: LanguageFiles) -> tuple[str, str]:
    """(`4 files (44%)`, `pkg/ (3), tests/ (1, test)`): how many files a language has, its share, and the folders
    that hold them, past `PLACES_SHOWN` counted."""
    shown, rest = shown_places(found)
    return file_count(found), ", ".join(f"{folder(place.directory)} {place_count(place)}" for place in shown) + rest


def files_by_language(analysis: Analysis) -> list[tuple[str, str, str]]:
    """(language, file count and share, folders) for each language and format, most files first."""
    if analysis.structure is None:
        return []
    return [(found.language, *language_files(found)) for found in analysis.structure.files]


def unrecognised(analysis: Analysis) -> str:
    """The suffixes no ecosystem recognised, most common first: languages the validator does not know yet."""
    if analysis.structure is None or not analysis.structure.unrecognised_suffixes:
        return ""
    return ", ".join(f"{suffix} ({count})" for suffix, count in analysis.structure.unrecognised_suffixes[:8])


def fact_kinds(analysis: Analysis) -> list[tuple[str, int]]:
    """Each kind of fact found, with how many, most first."""
    found = Counter(type(fact).__name__ for fact in analysis.facts.all)
    return sorted(found.items(), key=lambda item: (-item[1], item[0]))


__all__ = [
    "OUTCOMES",
    "PLACES_SHOWN",
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
    "file_count",
    "files_by_language",
    "grouped",
    "is_skipped",
    "judged_places",
    "language_files",
    "place_count",
    "place_label",
    "reading",
    "role_directories",
    "role_judgement",
    "role_line",
    "shown_places",
    "summary",
    "units",
    "unrecognised",
]
