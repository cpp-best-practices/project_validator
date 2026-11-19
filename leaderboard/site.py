"""The leaderboard's pages, for the documentation site (`tests/build_site.py --leaderboard DATA`) to render with its
navigation and style: Markdown by site path, and the files served as they are (badges, data).

    leaderboard/index.html                  every project ranked, then one board per language
    leaderboard/projects/<owner>--<repo>.html  a project: its numbers, history, what changed, next steps, cells
    leaderboard/badges/<owner>--<repo>.json    a shields.io endpoint: `project_validator | Level 3 · 91%`
    leaderboard/data/latest.json            every project's numbers, for anyone to use

Boards rank by level, then completeness; depth only breaks ties, since it is the least comparable number.
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from leaderboard import Entry
from leaderboard.history import latest, movement, previous, ranked, read_history

NEXT_STEPS = 10
SPARKLINE_NIGHTS = 60
_BADGE_COLORS = ("red", "orange", "yellow", "yellowgreen", "brightgreen")


def _text(value: object) -> str:
    """Text safe in a Markdown table cell."""
    return html.escape(str(value)).replace("|", "\\|").replace("\n", " ")


def percent(value: object) -> str:
    return f"{math.floor(round(float(value) * 100, 6))}%" if isinstance(value, int | float) else "-"


def _score(result: Mapping[str, object]) -> Mapping[str, object] | None:
    scored = result.get("score")
    return scored if isinstance(scored, dict) else None


def _numbers(result: Mapping[str, object]) -> tuple[str, str, str]:
    scored = _score(result)
    if scored is None:
        return "-", "-", "-"
    return str(scored["level"]), percent(scored["completeness"]), str(scored["depth"])


def _slug(name: str) -> str:
    return name.replace("/", "--")


def _row(position: int, result: Mapping[str, object], changes: Sequence[str], *, language: bool) -> str:
    name = str(result["name"])
    level, completeness, depth = _numbers(result)
    cells = [str(position), f"[{_text(name)}](projects/{_slug(name)}.md)"]
    if language:
        cells.append(_text(result["language"]))
    status = "error: " + _text(result["error"]) if "error" in result and _score(result) is None else ""
    cells += [level, completeness, depth, status or _text(", ".join(changes) or "-")]
    return "| " + " | ".join(cells) + " |"


def _board(results: Sequence[Mapping[str, object]], changes: Mapping[str, list[str]], *, language: bool) -> list[str]:
    header = ["#", "Project", *(["Language"] if language else []), "Level", "Completeness", "Depth", "Since last night"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += [
        _row(position, result, changes[str(result["name"])], language=language)
        for position, result in enumerate(ranked(results), 1)
    ]
    return lines


def index(
    listed: Sequence[Entry], results: Mapping[str, Mapping[str, object]], changes: Mapping[str, list[str]]
) -> str:
    lines = [
        "# Leaderboard",
        "",
        "Open-source projects that opted in, scored every night by the latest validator with `--score` "
        "([how the score works](../docs/score.md)). Boards rank by **level**, then **completeness**; depth only "
        "breaks ties. The score is a preview: it measures tooling coverage, not code quality. Seeds await a "
        "maintainer's confirmation. To add a project, see [how to join](README.md).",
        "",
    ]
    shown = [results[entry.name] for entry in listed if entry.name in results]
    if not shown:
        lines += ["No nightly results yet. The projects listed:", ""]
        lines += [f"- [{_text(entry.name)}]({entry.url}) ({_text(entry.language)})" for entry in listed]
        return "\n".join(lines) + "\n"
    lines += ["## All languages", "", *_board(shown, changes, language=True), "", "## By language", ""]
    for language in sorted({str(result["language"]) for result in shown}, key=str.lower):
        board = [result for result in shown if result["language"] == language]
        lines += [f"### {_text(language)}", "", *_board(board, changes, language=False), ""]
    return "\n".join(lines)


def sparkline(values: Sequence[float], width: int = 240, height: int = 40) -> str:
    """An inline SVG of the values (completeness, 0 to 1) over the nights, oldest first."""
    if len(values) < 2:
        return ""
    step = width / (len(values) - 1)
    points = " ".join(f"{index * step:.1f},{height - value * height:.1f}" for index, value in enumerate(values))
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="completeness over the last {len(values)} nights">'
        f'<polyline fill="none" stroke="#0550ae" stroke-width="2" points="{points}"/></svg>'
    )


def _facts(entry: Entry | None, result: Mapping[str, object]) -> list[str]:
    name = str(result["name"])
    url = entry.url if entry else f"https://github.com/{name}"
    facts = [f"- Repository: [{_text(name)}]({url}), on the {_text(result['language'])} board"]
    if result.get("seed"):
        facts.append("- A seed: awaiting a maintainer's confirmation")
    if commit := result.get("commit"):
        facts.append(f"- Commit evaluated: [{str(commit)[:12]}]({url}/commit/{commit})")
    scored = _score(result)
    version = f", score version {scored['version']}" if scored else ""
    facts.append(
        f"- Evaluated {_text(result.get('evaluated', '?'))} by validator {str(result.get('validator'))[:12]}{version}"
    )
    if unknowns := result.get("unknowns"):
        facts.append(f"- {unknowns} check(s) judged by what could be read (`--allow-unknown`): validator gaps to fix")
    return facts


def _opportunities(scored: Mapping[str, object]) -> list[str]:
    found = scored.get("opportunities")
    opportunities = found if isinstance(found, list) else []
    if not opportunities:
        return ["Every applicable cell is covered."]
    lines = ["| Check | Where | Tier | Now | Completeness | Depth | Level |", "|---|---|---|---|---|---|---|"]
    for opportunity in opportunities[:NEXT_STEPS]:
        where = " in ".join(part for part in (opportunity["ecosystem"], opportunity["unit"]) if part) or "the project"
        level = (
            f"unlocks {opportunity['unlocks']}"
            if opportunity.get("unlocks")
            else (f"toward {opportunity['blocks']}" if opportunity.get("blocks") else "")
        )
        lines.append(
            f"| `{_text(opportunity['check'])}` | {_text(where)} | {opportunity['tier']} | {opportunity['status']} "
            f"| +{float(opportunity['completeness']):.1%} | +{opportunity['depth']} | {level} |"
        )
    if len(opportunities) > NEXT_STEPS:
        lines += ["", f"And {len(opportunities) - NEXT_STEPS} more."]
    return lines


def _cells(scored: Mapping[str, object]) -> list[str]:
    found = scored.get("cells")
    cells = found if isinstance(found, list) else []
    lines = [
        "| Check | Level | Ecosystem | Unit | Tier | Status | Tools | Points |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cell in sorted(cells, key=lambda cell: (cell["level"], cell["check"], cell["unit"], cell["ecosystem"])):
        points = str(cell["points"]) if cell["counted"] else f"{cell['points']} (locked)"
        lines.append(
            f"| `{_text(cell['check'])}` | {cell['level']} | {_text(cell['ecosystem'] or '-')} "
            f"| {_text(cell['unit'] or '-')} | {cell['tier']} | {cell['status']} "
            f"| {_text(', '.join(cell['tools']) or '-')} | {points} |"
        )
    return lines


def _history_line(history: Sequence[Mapping[str, object]]) -> str:
    values = [float(value) for night in history if isinstance(value := night.get("completeness"), int | float)]
    return sparkline(values[-SPARKLINE_NIGHTS:])


def project_page(
    entry: Entry | None,
    result: Mapping[str, object],
    history: Sequence[Mapping[str, object]],
    changes: Sequence[str],
    badge_url: str,
) -> str:
    lines = [f"# {_text(result['name'])}", "", *_facts(entry, result), ""]
    scored = _score(result)
    if scored is None:
        lines += [f"Not scored tonight: {_text(result.get('error', 'no result'))}", ""]
        return "\n".join(lines)
    locked = (
        f" ({scored['locked_depth']} more locked until the levels below are complete)" if scored["locked_depth"] else ""
    )
    level, completeness, depth = _numbers(result)
    lines += [f"**Level {level} · {completeness} complete · {depth} depth**{locked}", ""]
    if drawn := _history_line(history):
        lines += [drawn, ""]
    lines += ["## Since last night", "", _text(", ".join(changes) or "No change."), ""]
    lines += ["## Next steps", "", *_opportunities(scored), ""]
    lines += ["## Cells", "", *_cells(scored), ""]
    return "\n".join([*lines, *_badge_section(badge_url)])


def _badge_section(badge_url: str) -> list[str]:
    image = f"![project_validator score](https://img.shields.io/endpoint?url={badge_url})"
    return ["## Badge", "", image, "", "```markdown", image, "```", ""]


def badge(result: Mapping[str, object]) -> dict[str, object]:
    """A shields.io endpoint for the project's README."""
    scored = _score(result)
    if scored is None:
        return {"schemaVersion": 1, "label": "project_validator", "message": "error", "color": "lightgrey"}
    level = int(str(scored["level"]))
    message = f"Level {level} · {percent(scored['completeness'])}"
    return {"schemaVersion": 1, "label": "project_validator", "message": message, "color": _BADGE_COLORS[level]}


def _summary(result: Mapping[str, object]) -> dict[str, object]:
    scored = _score(result) or {}
    return {
        "name": result["name"],
        "language": result["language"],
        "commit": result.get("commit"),
        "evaluated": result.get("evaluated"),
        **{key: scored.get(key) for key in ("version", "level", "completeness", "depth")},
    }


def build(listed: Sequence[Entry], data: Path | None, pages_url: str) -> tuple[dict[str, str], dict[str, str]]:
    """The leaderboard's pages (Markdown by site path) and its other files (text by site path), from the results in
    `data` (none yet when it is None or empty). `pages_url` is where the site is published, for the badges."""
    results = latest(data) if data is not None else {}
    by_name = {entry.name: entry for entry in listed}
    current = {name: result for name, result in results.items() if name in by_name}
    changes = {
        name: movement(previous(data, _slug(name)) if data else None, result) for name, result in current.items()
    }
    pages = {"leaderboard/index.html": index(listed, current, changes)}
    files: dict[str, str] = {}
    for name, result in current.items():
        slug = _slug(name)
        history = read_history(data / "history" / f"{slug}.jsonl") if data else []
        badge_url = f"{pages_url.rstrip('/')}/leaderboard/badges/{slug}.json"
        pages[f"leaderboard/projects/{slug}.html"] = project_page(
            by_name[name], result, history, changes[name], badge_url
        )
        files[f"leaderboard/badges/{slug}.json"] = json.dumps(badge(result), sort_keys=True) + "\n"
    summaries = [_summary(result) for result in ranked(list(current.values()))]
    files["leaderboard/data/latest.json"] = json.dumps(summaries, indent=2, sort_keys=True) + "\n"
    return pages, files
