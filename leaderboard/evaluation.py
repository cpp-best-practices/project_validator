"""Scoring a leaderboard project: fetch its branch as it is now (shallowly), run every check on it, and keep the score
and what each check said.

The validator parses build files and never runs the project's code, so evaluating an untrusted repository is safe;
`--build` stays off. The results are judged with `--allow-unknown`, so a construct the validator can not read yet does
not cost the project points; how many checks only that saved is recorded as `unknowns`, a validator gap to fix (as
the corpus records it). A crash is recorded, not raised: the board shows it, and it is a validator bug to file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from leaderboard import Entry
from project_validator.analysis import from_reports
from project_validator.core import Context, Options, Project, Status
from project_validator.plugins import discover
from project_validator.runner import Report, run_checks
from project_validator.score import score
from project_validator.views.html import render as html_report

# The key of a result that holds its HTML report, which `write` puts beside the JSON rather than in it.
REPORT = "report"


def _git(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is installed wherever this runs
        raise RuntimeError("git is needed to fetch the leaderboard projects")
    return subprocess.run(  # noqa: S603 - argv list, no shell
        [git, "-C", str(directory), *arguments], capture_output=True, text=True, check=False
    )


def fetch(entry: Entry, cache: Path, url: str | None = None) -> tuple[Path, str]:
    """The project's checkout at the head of its branch (the default branch unless the entry names one), fetched
    shallowly into `cache` (reusing a checkout already there), and the commit it is at."""
    directory = cache / entry.slug
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / ".git").is_dir():
        _git(directory, "init", "--quiet")
        _git(directory, "remote", "add", "origin", url or f"{entry.url}.git")
    for name, step in (
        ("fetch", ("fetch", "--quiet", "--depth", "1", "origin", entry.branch or "HEAD")),
        ("checkout", ("-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", "FETCH_HEAD")),
        ("clean", ("clean", "--quiet", "-ffdx")),
    ):
        done = _git(directory, *step)
        if done.returncode != 0:
            raise RuntimeError(f"{entry.name}: git {name} failed: {done.stderr.strip()}")
    return directory, _git(directory, "rev-parse", "HEAD").stdout.strip()


def _judged(entry: Entry, directory: Path) -> tuple[list[Report], list[Report], Context, list[str]]:
    """Every check's report on the checkout, judged strictly and with `--allow-unknown` (the facts are extracted
    once), the context, and the name of every check."""
    plugins = discover()
    project = Project(directory.resolve(), frozenset(PurePosixPath(path) for path in entry.exclude), entry.auxiliary)
    context = Context(project, plugins.providers, Options())
    strict = run_checks(plugins.checks, context)
    context.options = Options(allow_unknown=True)
    return strict, run_checks(plugins.checks, context), context, [found.name for found in plugins.checks]


def _stamp(entry: Entry, validator: str, now: datetime | None) -> dict[str, object]:
    return {
        "name": entry.name,
        "language": entry.language,
        "seed": entry.seed,
        "validator": validator,
        "evaluated": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def evaluate(
    entry: Entry, directory: Path, *, commit: str, validator: str, now: datetime | None = None
) -> dict[str, object]:
    """The project's result: its score (judged with `--allow-unknown`), each check's status and message, and how many
    checks erred only for want of `--allow-unknown`."""
    strict, judged, context, every_check = _judged(entry, directory)
    result = _stamp(entry, validator, now) | {
        "commit": commit,
        "unknowns": sum(
            1
            for before, after in zip(strict, judged, strict=True)
            if before.result.status is Status.ERROR and after.result.status is not Status.ERROR
        ),
        "checks": [
            {"check": report.check.name, "status": str(report.result.status), "message": report.result.message}
            for report in judged
        ],
    }
    if (failure := context.extraction_error) is not None:
        result["error"] = str(failure).replace(str(directory.resolve()), "<checkout>")
    result["score"] = score(judged, every_check).as_dict()
    result[REPORT] = html_report(from_reports(context, judged, every_check))
    return result


def failed(entry: Entry, error: str, *, validator: str, now: datetime | None = None) -> dict[str, object]:
    """The result of a project that could not be fetched: on the board, unscored, with why."""
    return _stamp(entry, validator, now) | {"error": error}


def write(result: dict[str, object], directory: Path) -> Path:
    """Write the result as `<slug>.json` in `directory`, and its HTML report, if any, beside it as `<slug>.html`."""
    directory.mkdir(parents=True, exist_ok=True)
    result = dict(result)
    report = result.pop(REPORT, None)
    path = directory / f"{str(result['name']).replace('/', '--')}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    if isinstance(report, str):
        path.with_suffix(".html").write_text(report, encoding="utf-8")
    return path
