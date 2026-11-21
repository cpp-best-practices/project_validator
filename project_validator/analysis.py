"""One analysis of a project: what was detected and how it was read, each check's result and the score. Every view
(plain text, the console, markdown, JSON, the HTML report, the TUI) renders an `Analysis`, so they all tell the same
story.

`analyse` runs the extraction and the checks, telling the context's observers what it does (`Progress`), so a view
can show it while it works.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from project_validator import __version__
from project_validator.core import Check, Context, ExtractionError, Observer, Progress
from project_validator.ecosystems import formats
from project_validator.facts import Facts
from project_validator.facts.auxiliary import selectors
from project_validator.facts.roles import AUXILIARY
from project_validator.facts.structure import SourceFile
from project_validator.project_map import ProjectStructure
from project_validator.runner import Report, run_checks
from project_validator.score import Score, score

# How many directories a role summary names.
ROLE_DIRECTORIES = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class Stage:
    """An extraction stage: how long it took and how many facts it found."""

    name: str
    seconds: float
    found: int

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "seconds": round(self.seconds, 4), "found": self.found}


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleSummary:
    """The project's own sources in one role (product, test, example, docs, tooling, benchmark, vendored): the
    top-level directories they are in, how many files, in which languages, and whether `--auxiliary` names the role."""

    role: str
    directories: tuple[str, ...]
    files: int
    languages: tuple[str, ...]
    auxiliary: bool = False

    @property
    def suggestion(self) -> str | None:
        """The option that would judge this code as auxiliary, when it could be and is not yet."""
        return f"--auxiliary {self.role}" if self.role in AUXILIARY and not self.auxiliary else None

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "directories": list(self.directories),
            "files": self.files,
            "languages": list(self.languages),
            "auxiliary": self.auxiliary,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Git:
    """The checkout the project is in, if any: its commit, and where its files can be seen on the web."""

    commit: str | None = None
    branch: str | None = None
    web: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"commit": self.commit, "branch": self.branch, "web": self.web}


@dataclass(frozen=True, slots=True, kw_only=True)
class Analysis:
    project: Path
    validator: str
    options: dict[str, object]
    structure: ProjectStructure | None
    facts: Facts
    reports: tuple[Report, ...]
    score: Score | None
    stages: tuple[Stage, ...]
    roles: tuple[RoleSummary, ...]
    seconds: float
    git: Git = field(default_factory=Git)
    error: ExtractionError | None = None
    # The paths git ignores, left out of the project (see `Project.ignored`).
    ignored: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.project.name

    def as_dict(self) -> dict[str, object]:
        from project_validator.cli import report_dicts  # the results as --format json prints them

        return {
            "project": {"name": self.name, "path": str(self.project)},
            "validator": self.validator,
            "options": self.options,
            "seconds": round(self.seconds, 3),
            "git": self.git.as_dict(),
            "stages": [stage.as_dict() for stage in self.stages],
            "structure": self.structure.as_dict() if self.structure is not None else None,
            "roles": [role.as_dict() for role in self.roles],
            "results": report_dicts(list(self.reports)),
            "score": self.score.as_dict() if self.score is not None else None,
        }


def _top(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else "."


def roles(facts: Facts, named: Iterable[str] = ()) -> tuple[RoleSummary, ...]:
    """The project's sources by role (its code, not its data files), the product first; `named` are the roles
    `--auxiliary` names."""
    by_role: dict[str, list[SourceFile]] = {}
    known = formats()
    for source in facts.of(SourceFile):
        if (source.language is not None and source.language not in known) or source.vendored:
            by_role.setdefault(source.role, []).append(source)
    named = set(named)
    order = sorted(by_role, key=lambda role: (role != "product", role == "vendored", role))
    return tuple(
        RoleSummary(
            role=role,
            directories=tuple(dict.fromkeys(_top(source.path) for source in by_role[role]))[:ROLE_DIRECTORIES],
            files=len(by_role[role]),
            languages=tuple(sorted({source.language for source in by_role[role] if source.language})),
            auxiliary=role in named,
        )
        for role in order
    )


def _git(directory: Path, *arguments: str) -> str | None:
    try:
        found = subprocess.run(  # noqa: S603 - git, with the validator's own arguments
            ["git", "-C", str(directory), *arguments],  # noqa: S607 - git from PATH, as the user runs it
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return found.stdout.strip() or None if found.returncode == 0 else None


_SSH = re.compile(r"^(?:ssh://)?git@(?P<host>[^:/]+)[:/](?P<path>.+?)(?:\.git)?/?$")
_HTTPS = re.compile(r"^https?://(?:[^@/]+@)?(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?/?$")


def web_url(remote: str) -> str | None:
    """Where a git remote's files can be seen in a browser (`git@github.com:o/r.git` is https://github.com/o/r)."""
    found = _SSH.match(remote) or _HTTPS.match(remote)
    return f"https://{found['host']}/{found['path']}" if found else None


def git_of(directory: Path) -> Git:
    """The checkout `directory` is the top of, if it is one."""
    top = _git(directory, "rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != directory.resolve():
        return Git()
    remote = _git(directory, "remote", "get-url", "origin")
    return Git(
        commit=_git(directory, "rev-parse", "HEAD"),
        branch=_git(directory, "rev-parse", "--abbrev-ref", "HEAD"),
        web=web_url(remote) if remote else None,
    )


_LINE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")


def file_url(git: Git, origin: str) -> str | None:
    """Where a fact's origin (`src/a.py`, `src/a.py:3`) can be seen on the web, at the commit analysed."""
    if git.web is None or git.commit is None or not origin or origin == ".":
        return None
    path, line = origin, None
    if found := _LINE.match(origin):
        path, line = found["path"], found["line"]
    path = path.split(":", 1)[0]
    return f"{git.web}/blob/{git.commit}/{path}{f'#L{line}' if line else ''}"


def folder_url(git: Git, directory: str) -> str | None:
    """Where a folder of the project ("." for the root) can be seen on the web, at the commit analysed."""
    if git.web is None or git.commit is None:
        return None
    tree = f"{git.web}/tree/{git.commit}"
    return tree if directory == "." else f"{tree}/{directory}"


def _options(context: Context) -> dict[str, object]:
    options = context.options
    return {
        "build": options.build,
        "allow_unknown": options.allow_unknown,
        "allow_official_tags": options.allow_official_tags,
        "max_file_size": options.max_file_size,
        "exclude": sorted(map(str, context.project.excluded)),
        "auxiliary": list(context.project.auxiliary),
    }


def analyse(
    context: Context,
    checks: Sequence[Check],
    *,
    every_check: Iterable[str] | None = None,
    scored: bool = True,
    progress: Observer | None = None,
) -> Analysis:
    """Extract the facts about the project `context` reads and run `checks` on it, telling `progress` (and the
    context's other observers) what it does. The score counts `every_check` (the names of every check there is,
    `checks` by default) for the top level."""
    stages: list[Stage] = []
    context.observe(lambda event: _record(event, stages))
    if progress is not None:
        context.observe(progress)
    started = time.perf_counter()
    with contextlib.suppress(ExtractionError):
        _ = context.facts  # first, so that the stages are told before the checks; a failure is kept for the checks
    reports = tuple(run_checks(checks, context))
    names = [check.name for check in checks] if every_check is None else list(every_check)
    return _finished(context, reports, tuple(stages), score_of=names if scored else None, started=started)


def _finished(
    context: Context,
    reports: tuple[Report, ...],
    stages: tuple[Stage, ...],
    *,
    score_of: list[str] | None,
    started: float,
) -> Analysis:
    """The analysis of a run: scored against `score_of` (every check's name), unless it is None."""
    error = context.extraction_error
    facts = Facts(()) if error is not None else context.facts
    return Analysis(
        project=context.project.root,
        validator=__version__,
        options=_options(context),
        structure=None if error is not None else context.structure,
        facts=facts,
        reports=reports,
        score=score(reports, score_of) if score_of is not None and error is None else None,
        stages=stages,
        roles=roles(facts, selectors(facts).roles if error is None else ()),
        seconds=time.perf_counter() - started,
        git=git_of(context.project.root),
        error=error,
        ignored=context.project.ignored(),
    )


def from_reports(context: Context, reports: Sequence[Report], every_check: Iterable[str]) -> Analysis:
    """The analysis of reports already run on `context` (the stages are not known then)."""
    return _finished(context, tuple(reports), (), score_of=list(every_check), started=time.perf_counter())


def _record(event: Progress, stages: list[Stage]) -> None:
    if event.kind == "stage" and event.done:
        stages.append(Stage(name=event.name, seconds=event.seconds, found=event.found))


__all__ = [
    "Analysis",
    "Git",
    "Progress",
    "RoleSummary",
    "Stage",
    "analyse",
    "file_url",
    "from_reports",
    "git_of",
    "roles",
    "web_url",
]
