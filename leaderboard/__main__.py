"""The leaderboard's commands, as the workflows run them (see leaderboard/README.md).

python -m leaderboard matrix                         the names, as JSON, for a job matrix
python -m leaderboard evaluate OUT [NAME...]         fetch and score projects (default: all) into OUT/<slug>.json
python -m leaderboard record RESULTS DATA --date D   add a night's results to the data directory
python -m leaderboard check --base BASE.toml --out PREVIEW.md
                                                     check the entries a pull request adds, and preview them
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from leaderboard import MANIFEST, Entry, ManifestError, by_name, entries, parse
from leaderboard.evaluation import evaluate, failed, fetch, write
from leaderboard.history import record
from leaderboard.rules import Repository, changed, duplicates, github_repository, problems, token
from leaderboard.site import percent
from project_validator.score import SCORE_VERSION

PREVIEW_MARKER = "<!-- leaderboard-preview -->"
PREVIEW_STEPS = 5
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "project_validator-leaderboard"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m leaderboard", description="Score the leaderboard's projects.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="the project list (default: projects.toml)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("matrix", help="print the projects' names as JSON")
    evaluating = commands.add_parser("evaluate", help="fetch and score projects")
    evaluating.add_argument("out", type=Path, help="the directory to write each result to")
    evaluating.add_argument("names", nargs="*", help="the projects (default: every one)")
    evaluating.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="where the checkouts are kept")
    evaluating.add_argument("--validator", default="local", help="the validator's commit, as recorded")
    recording = commands.add_parser("record", help="add a night's results to the data directory")
    recording.add_argument("results", type=Path)
    recording.add_argument("data", type=Path)
    recording.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    checking = commands.add_parser("check", help="check the entries a pull request adds or changes, and preview them")
    checking.add_argument("--base", type=Path, required=True, help="the base branch's projects.toml (may be absent)")
    checking.add_argument("--out", type=Path, required=True, help="where to write the preview (Markdown)")
    checking.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    checking.add_argument("--validator", default="local")
    return parser


def _evaluated(entry: Entry, cache: Path, validator: str) -> dict[str, object]:
    try:
        directory, commit = fetch(entry, cache)
    except RuntimeError as error:
        return failed(entry, str(error), validator=validator)
    return evaluate(entry, directory, commit=commit, validator=validator)


def _preview_lines(entry: Entry, found: list[str], result: dict[str, object] | None) -> list[str]:
    lines = [f"### [{entry.name}]({entry.url}) on the {entry.language} board", ""]
    if found:
        return [*lines, "Can not join yet:", "", *(f"- {problem}" for problem in found), ""]
    scored = result.get("score") if result else None
    if not isinstance(scored, dict):
        return [*lines, f"Could not be scored: {result.get('error') if result else 'no result'}", ""]
    complete = percent(scored["completeness"])
    lines += [f"**Level {scored['level']} · {complete} complete · {scored['depth']} depth**", ""]
    opportunities = scored.get("opportunities")
    if isinstance(opportunities, list) and opportunities:
        lines += ["Next steps that would raise it most:", ""]
        for opportunity in opportunities[:PREVIEW_STEPS]:
            where = " in ".join(part for part in (opportunity["ecosystem"], opportunity["unit"]) if part)
            lines.append(f"- `{opportunity['check']}`{f' ({where})' if where else ''}")
        lines.append("")
    return lines


def check(
    base: Sequence[Entry],
    head: Sequence[Entry],
    repository: Callable[[str], Repository],
    evaluated: Callable[[Entry], dict[str, object]],
) -> tuple[bool, str]:
    """Whether the entries `head` adds or changes may join, and the preview to comment: each entry's problems, or its
    score and top next steps."""
    lines = [PREVIEW_MARKER, "## Leaderboard preview", ""]
    ok = True
    if twice := duplicates(head):
        ok = False
        lines += [f"Listed more than once: {', '.join(twice)}", ""]
    new = changed(base, head)
    if not new:
        lines += ["No entry is added or changed.", ""]
    for entry in new:
        found = problems(entry, repository(entry.name))
        ok = ok and not found
        lines += _preview_lines(entry, found, None if found else evaluated(entry))
    lines.append(f"Scored by score version {SCORE_VERSION} (a preview). The board ranks by level, then completeness.")
    return ok, "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        listed = entries(arguments.manifest)
    except ManifestError as error:
        print(f"leaderboard: {error}", file=sys.stderr)
        return 1
    if arguments.command == "matrix":
        print(json.dumps([entry.name for entry in listed]))
    elif arguments.command == "evaluate":
        for entry in by_name(arguments.names, listed) if arguments.names else listed:
            print(write(_evaluated(entry, arguments.cache, arguments.validator), arguments.out))
    elif arguments.command == "record":
        for name in record(arguments.results, arguments.data, arguments.date):
            print(name)
    else:
        base_text = arguments.base.read_text(encoding="utf-8") if arguments.base.is_file() else ""
        ok, preview = check(
            parse(base_text),
            listed,
            lambda name: github_repository(name, token()),
            lambda entry: _evaluated(entry, arguments.cache, arguments.validator),
        )
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(preview, encoding="utf-8")
        print(preview)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":  # pragma: no cover - run as a module
    sys.exit(main())
