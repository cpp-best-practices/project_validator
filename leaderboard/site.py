"""The leaderboard's pages, for the documentation site (`tests/build_site.py --leaderboard DATA`) to render with its
navigation and style: each page's source by site path (a title heading, then HTML), and the files served as they are.

    leaderboard/index.html                     every project ranked, with a tab per language
    leaderboard/projects/<owner>--<repo>.html  a project: its score, history, what changed, next steps, every gate
    leaderboard/reports/<owner>--<repo>.html   its full HTML report, from the night it was scored
    leaderboard/badges/<owner>--<repo>.json    a shields.io endpoint: `project_validator | 91% · Level 3`
    leaderboard/data/latest.json               every project's numbers, for anyone to use

Boards rank by the score's percent (100%: every quality gate that applies is in place; extra credit above), then
level, and divide by language, by kind (the entry's) and by size (`SIZES`, by the product's lines of code): the tabs
filter the board, and the ranks count within what they show. Everything the projects supply is escaped.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from leaderboard import Entry
from leaderboard.history import latest, movement, previous, ranked, read_history, scored
from project_validator.core import Status
from project_validator.losses import in_points
from project_validator.score import SCORE_VERSION, where
from project_validator.views.html import bar, e, pill, ring, table

NEXT_STEPS = 10
# The sizes a project's product code is ranked within, by its lines: under each bound, that size; past the last, large.
SIZES = ((10_000, "small"), (100_000, "medium"))
LARGE = "large"
SPARKLINE_NIGHTS = 60
_BADGE_COLORS = ("red", "orange", "yellow", "yellowgreen", "brightgreen")


def size(lines: object) -> str:
    """The size a project of `lines` lines of product code is ranked within; "" when it was never measured."""
    if not isinstance(lines, int):
        return ""
    return next((name for bound, name in SIZES if lines < bound), LARGE)


def percent(value: object) -> str:
    """A score's percent as the boards show it: floored, so 99.9% is never shown as 100%."""
    return f"{math.floor(round(float(value), 6))}%" if isinstance(value, int | float) else "-"


def _score(result: Mapping[str, object]) -> Mapping[str, object] | None:
    return scored(result)


def _unscored(result: Mapping[str, object]) -> str:
    """Why a result has no score to show: its error, or the earlier score version that scored it."""
    found = result.get("score")
    if isinstance(found, dict):
        return f"scored by score version {found.get('version')}; this version scores it next"
    return str(result.get("error", "no result"))


def _slug(name: str) -> str:
    return name.replace("/", "--")


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _level(scored: Mapping[str, object]) -> str:
    return f'<span class="chip level">Level {e(scored["level"])} · {e(scored["level_name"])}</span>'


def _score_cell(scored: Mapping[str, object] | None) -> str:
    if scored is None:
        return '<span class="muted">-</span>'
    return f'<div class="scorebar">{bar(_number(scored["percent"]))}<strong>{percent(scored["percent"])}</strong></div>'


def _row(position: int, result: Mapping[str, object], changes: Sequence[str], kind: str) -> str:
    name, language, scored = str(result["name"]), str(result["language"]), _score(result)
    seed = ' <span class="chip">seed</span>' if result.get("seed") else ""
    if scored is None:
        status = f'<span class="pill s-ERROR">error</span> <span class="muted">{e(result.get("error", ""))}</span>'
    else:
        status = f'<span class="muted">{e(", ".join(changes) or "-")}</span>'
    lines, sized = result.get("lines"), size(result.get("lines"))
    measured = f'{e(sized)} <span class="muted">{lines:,} lines</span>' if isinstance(lines, int) else ""
    return (
        f'<tr data-language="{e(language)}" data-kind="{e(kind)}" data-size="{e(sized)}">'
        f'<td class="rank">{position}</td>'
        f'<td><a href="projects/{e(_slug(name))}.html"><strong>{e(name)}</strong></a>{seed}</td>'
        f"<td>{e(language)}</td><td>{e(kind)}</td><td>{measured}</td><td>{_score_cell(scored)}</td>"
        f"<td>{_level(scored) if scored else ''}</td><td>{status}</td></tr>"
    )


def _tab_group(name: str, everything: str, values: Sequence[str]) -> str:
    """A row of tabs that filters the board by `name` (language, kind, size): one for every project, one per value."""
    buttons = [
        f'<button class="tab active" data-filter="{name}" data-value="">{everything} <span class="n">{len(values)}'
        "</span></button>"
    ]
    for value in sorted(set(values), key=str.lower):
        buttons.append(
            f'<button class="tab" data-filter="{name}" data-value="{e(value)}">{e(value)} '
            f'<span class="n">{values.count(value)}</span></button>'
        )
    return f'<div class="tabs" role="tablist">{"".join(buttons)}</div>'


def _tabs(results: Sequence[Mapping[str, object]], kinds: Mapping[str, str]) -> str:
    sized = [size(result.get("lines")) for result in results]
    return (
        _tab_group("language", "All languages", [str(result["language"]) for result in results])
        + _tab_group("kind", "All kinds", [kinds[str(result["name"])] for result in results])
        + _tab_group("size", "All sizes", [found for found in sized if found])
    )


# The tabs filter the rows by every group at once, and the ranks count what is shown.
BOARD_SCRIPT = (
    "<script>var f={};document.querySelectorAll('.tabs .tab').forEach(function(t){t.addEventListener('click',"
    "function(){var g=t.dataset.filter,n=0;f[g]=t.dataset.value;document.querySelectorAll('.tabs .tab').forEach("
    "function(b){if(b.dataset.filter===g)b.classList.toggle('active',b===t)});"
    "document.querySelectorAll('.ranking tbody tr').forEach(function(r){var ok=Object.keys(f).every(function(k){"
    "return !f[k]||r.dataset[k]===f[k]});r.style.display=ok?'':'none';if(ok){n+=1;"
    "r.querySelector('.rank').textContent=n}})})});</script>"
)


INTRO = (
    "Open-source projects that opted in, scored every night by the latest validator. **100% means every quality "
    "gate that applies to the project is in place**; complementary tools earn extra credit above it "
    "([how the score works](../docs/score.md)). The score measures tooling, not code quality: the board is a "
    "showcase, not a wall of shame. Seeds await a maintainer's confirmation. [How to join](README.md)."
)


def index(
    listed: Sequence[Entry], results: Mapping[str, Mapping[str, object]], changes: Mapping[str, list[str]]
) -> str:
    shown = [results[entry.name] for entry in listed if entry.name in results]
    if not shown:
        cards = "".join(
            f'<div class="card"><a href="{e(entry.url)}"><strong>{e(entry.name)}</strong></a>'
            f'<div class="muted">{e(entry.language)}</div></div>'
            for entry in listed
        )
        return (
            f'# Leaderboard\n\n{INTRO}\n\n<div class="board"><h2>No nightly results yet</h2>'
            f'<div class="grid three">{cards}</div></div>\n'
        )
    kinds = {entry.name: entry.kind for entry in listed}
    rows = "".join(
        _row(position, result, changes[str(result["name"])], kinds[str(result["name"])])
        for position, result in enumerate(ranked(shown), 1)
    )
    columns = ("#", "Project", "Language", "Kind", "Size", "Score", "Level", "Last change")
    head = "".join(f"<th>{name}</th>" for name in columns)
    return (
        f'# Leaderboard\n\n{INTRO}\n\n<div class="board">{_tabs(shown, kinds)}'
        f'<div class="card table-wrap"><table class="ranking"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody>'
        f"</table></div>{BOARD_SCRIPT}</div>\n"
    )


def sparkline(values: Sequence[float], width: int = 240, height: int = 40) -> str:
    """An inline SVG of the values (the score's percent) over the nights, oldest first, from 0 to 100% (or the most
    extra credit)."""
    if len(values) < 2:
        return ""
    top = max(100.0, *values)
    step = width / (len(values) - 1)
    points = " ".join(f"{index * step:.1f},{height - value / top * height:.1f}" for index, value in enumerate(values))
    return (
        f'<svg class="sparkline" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="the score over the last {len(values)} nights">'
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{points}"/></svg>'
    )


def _facts(entry: Entry | None, result: Mapping[str, object], report: bool) -> str:
    name = str(result["name"])
    url = entry.url if entry else f"https://github.com/{name}"
    facts = [f'<a href="{e(url)}">{e(name)}</a> on the {e(result["language"])} board']
    if result.get("seed"):
        facts.append("a seed, awaiting a maintainer's confirmation")
    if commit := result.get("commit"):
        facts.append(f'commit <a href="{e(url)}/commit/{e(commit)}"><code>{e(str(commit)[:12])}</code></a>')
    scored = _score(result)
    version = f", score version {e(scored['version'])}" if scored else ""
    facts.append(
        f"evaluated {e(result.get('evaluated', '?'))} by validator <code>{e(str(result.get('validator'))[:12])}</code>"
        f"{version}"
    )
    if unknowns := result.get("unknowns"):
        facts.append(f"{e(unknowns)} check(s) judged by what could be read (--allow-unknown): validator gaps to fix")
    if report:
        facts.append(f'<a href="../reports/{e(_slug(name))}.html"><strong>the full report →</strong></a>')
    return "".join(f"<li>{fact}</li>" for fact in facts)


def _step_row(step: Mapping[str, object]) -> tuple[str, ...]:
    where = " in ".join(str(part) for part in (step["ecosystem"], step["unit"]) if part and part != ".")
    needed = step.get("needed_for")
    verb = "completes" if step.get("completes") else "for"
    level = f' <span class="chip level">{verb} Level {e(needed)}</span>' if needed else ""
    return (
        f'<strong class="plus">+{_number(step["points"]):.1f}</strong>',
        f"<code>{e(step['check'])}</code>{level}",
        e(where or "the project"),
        pill(Status(str(step["status"]))),
        e(step.get("hint") or step.get("message") or ""),
    )


def losses_card(scored: Mapping[str, object]) -> str:
    """Where the score loses its points, by cause, and what corrects each: nothing for a night recorded before the
    score said."""
    found = scored.get("losses")
    if not isinstance(found, list) or not found:
        return ""
    rows = [
        (
            f'<strong style="color:var(--fail)">-{e(in_points(float(each["points"])))}</strong>',
            f"<strong>{e(each['title'])}</strong><br><span class=muted>{e(each['correct'])}</span>",
            "<br>".join(
                f"<code>{e(slot['check'])}</code> {e(where(slot['ecosystem'], slot['unit']))} "
                f'<span class="muted">{e(in_points(float(slot["points"])))}</span>'
                for slot in each["slots"][:NEXT_STEPS]
            ),
        )
        for each in found
    ]
    return f'<h2>Where points are lost</h2><div class="card">{table(("Points", "Cause", "Slots"), rows)}</div>'


def _next_steps(scored: Mapping[str, object]) -> str:
    found = scored.get("next_steps")
    steps = found if isinstance(found, list) else []
    if not steps:
        return "<p>Every quality gate that applies is in place.</p>"
    more = f'<p class="muted">And {len(steps) - NEXT_STEPS} more.</p>' if len(steps) > NEXT_STEPS else ""
    rows = [_step_row(step) for step in steps[:NEXT_STEPS]]
    return table(("Points", "Gate", "Where", "Now", "To do"), rows) + more


def _cell_row(cell: Mapping[str, object]) -> tuple[str, ...]:
    found = cell["tools"]
    tools = "".join(f'<span class="tool">{e(tool)}</span>' for tool in found) if isinstance(found, list) else ""
    extra = f" +{e(cell['extra'])}" if cell.get("extra") else ""
    return (
        f"<code>{e(cell['check'])}</code>",
        e(cell["level"]),
        e(cell["ecosystem"] or "the project"),
        e(cell["unit"] or "-"),
        e(cell["tier"]),
        pill(Status(str(cell["status"]))),
        f'<span class="tools">{tools}</span>' if tools else '<span class="muted">-</span>',
        f"{e(cell['filled'])} of {e(cell['weight'])}{extra}",
    )


def _cells(scored: Mapping[str, object]) -> str:
    found = scored.get("cells")
    cells = found if isinstance(found, list) else []
    ordered = sorted(cells, key=lambda cell: (cell["level"], cell["check"], cell["unit"], cell["ecosystem"]))
    headers = ("Gate", "Level", "Language", "Unit", "Code", "Status", "Tools", "Filled")
    return table(headers, [_cell_row(cell) for cell in ordered])


def _history(history: Sequence[Mapping[str, object]]) -> str:
    values = [
        float(value)
        for night in history
        if night.get("version") == SCORE_VERSION and isinstance(value := night.get("percent"), int | float)
    ]
    drawn = sparkline(values[-SPARKLINE_NIGHTS:], width=520, height=80)
    return drawn or '<p class="muted">The history starts after a second night.</p>'


def _badge_section(badge_url: str) -> str:
    image = f"![project_validator score](https://img.shields.io/endpoint?url={badge_url})"
    return (
        f'<h2>Badge</h2><div class="card"><p><img alt="project_validator score" '
        f'src="https://img.shields.io/endpoint?url={e(badge_url)}"></p><pre><code>{e(image)}</code></pre></div>'
    )


def project_page(
    entry: Entry | None,
    result: Mapping[str, object],
    history: Sequence[Mapping[str, object]],
    changes: Sequence[str],
    badge_url: str,
    *,
    report: bool = False,
) -> str:
    """A project's page: its score, the facts of its night, its history, what changed, next steps and every gate."""
    title = f"# {e(result['name'])}\n\n"
    scored = _score(result)
    facts = f'<ul class="facts-list">{_facts(entry, result, report)}</ul>'
    if scored is None:
        return title + f'<div class="card">{facts}<p>Not scored tonight: {e(_unscored(result))}</p></div>\n'
    value = _number(scored["percent"])
    since = "".join(f"<li>{e(change)}</li>" for change in changes) or "<li>No change.</li>"
    return title + (
        f'<div class="card project-hero">{ring(value, f"score {value:.0f} percent")}<div>'
        f'<div class="chips">{_level(scored)}<span class="chip">{e(_gates(scored))}</span></div>{facts}</div></div>'
        f'<div class="grid two" style="margin-top:1rem"><div class="card"><h3>The score, night by night</h3>'
        f'{_history(history)}</div><div class="card"><h3>Since it was last scored</h3><ul>{since}</ul></div></div>'
        f"{losses_card(scored)}"
        f'<h2>Next steps</h2><div class="card">{_next_steps(scored)}</div>'
        f'<h2>Every gate</h2><div class="card">{_cells(scored)}</div>{_badge_section(badge_url)}\n'
    )


def _gates(scored: Mapping[str, object]) -> str:
    """The score's summary without the percent and level the page shows already: `31 of 51 gates in place`."""
    return " · ".join(str(scored["summary"]).split(" · ")[2:])


def badge(result: Mapping[str, object]) -> dict[str, object]:
    """A shields.io endpoint for the project's README."""
    scored = _score(result)
    if scored is None:
        return {"schemaVersion": 1, "label": "project_validator", "message": "error", "color": "lightgrey"}
    level = int(str(scored["level"]))
    message = f"{percent(scored['percent'])} · Level {level}"
    return {"schemaVersion": 1, "label": "project_validator", "message": message, "color": _BADGE_COLORS[level]}


def _summary(result: Mapping[str, object], kind: str) -> dict[str, object]:
    scored = _score(result) or {}
    return {
        "name": result["name"],
        "language": result["language"],
        "kind": kind,
        "lines": result.get("lines"),
        "size": size(result.get("lines")),
        "commit": result.get("commit"),
        "evaluated": result.get("evaluated"),
        **{key: scored.get(key) for key in ("version", "percent", "level", "level_name", "filled", "slots")},
    }


def build(listed: Sequence[Entry], data: Path | None, pages_url: str) -> tuple[dict[str, str], dict[str, str]]:
    """The leaderboard's pages (by site path) and its other files (text by site path), from the results in `data`
    (none yet when it is None or empty). `pages_url` is where the site is published, for the badges."""
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
        report = data / "reports" / f"{slug}.html" if data else None
        if report is not None and report.is_file():
            files[f"leaderboard/reports/{slug}.html"] = report.read_text(encoding="utf-8")
        badge_url = f"{pages_url.rstrip('/')}/leaderboard/badges/{slug}.json"
        pages[f"leaderboard/projects/{slug}.html"] = project_page(
            by_name[name], result, history, changes[name], badge_url, report=f"leaderboard/reports/{slug}.html" in files
        )
        files[f"leaderboard/badges/{slug}.json"] = json.dumps(badge(result), sort_keys=True) + "\n"
    summaries = [_summary(result, by_name[str(result["name"])].kind) for result in ranked(list(current.values()))]
    files["leaderboard/data/latest.json"] = json.dumps(summaries, indent=2, sort_keys=True) + "\n"
    return pages, files


__all__ = ["badge", "build", "index", "percent", "project_page", "size", "sparkline"]
