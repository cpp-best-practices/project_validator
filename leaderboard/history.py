"""The leaderboard's memory: each night's results added to the data directory (the `leaderboard-data` branch), and what
changed since the night before.

    latest/<owner>--<repo>.json    tonight's full result (score, cells, next steps, each check's status)
    previous/<owner>--<repo>.json  the night before's, for what changed
    reports/<owner>--<repo>.html   tonight's full HTML report (the latest only)
    history/<owner>--<repo>.jsonl  one line per night: the date, commit, validator, score version, percent and level

A project whose numbers change while its commit does not was changed by the validator, not by its maintainers: the
movement says so, and the change is for the validator's developers to look at.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from leaderboard import Entry
from project_validator.score import SCORE_VERSION

SCORED = ("version", "percent", "level", "filled", "slots")
HISTORY_FIELDS = ("date", "commit", "validator", *SCORED)


def scored(result: Mapping[str, object] | None) -> Mapping[str, object] | None:
    """The result's score when this version of the score made it; None when it was not scored, or an earlier version
    scored it (other numbers, never compared with these)."""
    found = result.get("score") if result else None
    return found if isinstance(found, dict) and found.get("version") == SCORE_VERSION else None


def _read(path: Path) -> dict[str, object] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _summary(result: Mapping[str, object], date: str) -> dict[str, object]:
    scored = result.get("score")
    numbers = scored if isinstance(scored, dict) else {}
    line: dict[str, object] = {"date": date, "commit": result.get("commit"), "validator": result.get("validator")}
    line |= {key: numbers.get(key) for key in SCORED}
    return line


def record(results: Path, data: Path, date: str) -> list[str]:
    """Add the results in `results` (one JSON per project) to `data` as `date`'s; a night recorded twice keeps its
    last run. The names recorded."""
    recorded = []
    for path in sorted(results.glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        latest, previous = data / "latest" / path.name, data / "previous" / path.name
        history = data / "history" / f"{path.stem}.jsonl"
        for directory in (latest.parent, previous.parent, history.parent):
            directory.mkdir(parents=True, exist_ok=True)
        lines = read_history(history)
        if lines and lines[-1].get("date") == date:
            lines.pop()  # a rerun of the same night replaces it, and leaves the night before as the previous
        elif latest.is_file():
            previous.write_bytes(latest.read_bytes())
        lines.append(_summary(result, date))
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _keep_report(path.with_suffix(".html"), data / "reports" / f"{path.stem}.html")
        history.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in lines), encoding="utf-8")
        recorded.append(str(result["name"]))
    return recorded


def _keep_report(report: Path, kept: Path) -> None:
    """Keep tonight's HTML report of a project (the latest only), or none when tonight has none."""
    if report.is_file():
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(report.read_bytes())
    else:
        kept.unlink(missing_ok=True)


def read_history(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest(data: Path) -> dict[str, dict[str, object]]:
    """Tonight's result for each project recorded, by name."""
    found = {}
    for path in sorted((data / "latest").glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        found[str(result["name"])] = result
    return found


def previous(data: Path, slug: str) -> dict[str, object] | None:
    return _read(data / "previous" / f"{slug}.json")


def _tools(result: Mapping[str, object] | None) -> set[tuple[str, str]]:
    scored = result.get("score") if result else None
    cells = scored.get("cells", []) if isinstance(scored, dict) else []
    return {(str(cell["check"]), str(tool)) for cell in cells for tool in cell["tools"]}


def _numbers(result: Mapping[str, object] | None) -> tuple[float, float] | None:
    """The result's level and percent; None when it was not scored."""
    numbers = scored(result)
    if numbers is None:
        return None
    level, percent = numbers.get("level"), numbers.get("percent")
    return (
        float(level) if isinstance(level, int | float) else 0.0,
        float(percent) if isinstance(percent, int | float) else 0.0,
    )


def movement(before: Mapping[str, object] | None, after: Mapping[str, object]) -> list[str]:
    """What changed between two nights' results, in words: the tools that arrived or left (by check), the level and
    the percent; and, when the commit is the same, that the validator changed it."""
    if before is None:
        return ["new on the board"]
    changes = [f"+{tool} ({check})" for check, tool in sorted(_tools(after) - _tools(before))]
    changes += [f"-{tool} ({check})" for check, tool in sorted(_tools(before) - _tools(after))]
    old, new = _numbers(before), _numbers(after)
    if old and new:
        if old[0] != new[0]:
            changes.append(f"Level {old[0]:g} → {new[0]:g}")
        if round(new[1] - old[1], 1):
            changes.append(f"{new[1] - old[1]:+.1f} points")
    if changes and before.get("commit") == after.get("commit"):
        changes.append("same commit: the validator changed")
    return changes


def changed_since(listed: Sequence[Entry], data: Path, head: Callable[[str], str | None]) -> list[str]:
    """The names of the listed projects with something new to score since `data`'s results: a commit at the head of
    the branch (`head(name)`, None when it can not be told) that is not the last scored, no result yet, or a result of
    an earlier version of the score."""
    recorded = latest(data) if (data / "latest").is_dir() else {}
    return [
        entry.name
        for entry in listed
        if (result := recorded.get(entry.name)) is None
        or scored(result) is None
        or (commit := head(entry.name)) is None
        or commit != result.get("commit")
    ]


def ranked(results: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """The results in board order: by percent (extra credit included), then level; the unscored come last."""

    def key(result: Mapping[str, object]) -> tuple[int, float, float, str]:
        numbers = _numbers(result)
        if numbers is None:
            return (1, 0.0, 0.0, str(result["name"]).lower())
        level, percent = numbers
        return (0, -percent, -level, str(result["name"]).lower())

    return sorted(results, key=key)
