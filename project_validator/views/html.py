"""The HTML report: one self-contained file (no network, nothing to install) with everything the analysis knows.

- **Overview**: the score ring, the level, the status counts, each language's share of its gates, the next steps.
- **Detected**: the languages and formats and what recognised each, the units, the code in each role (and the
  option that would judge it as auxiliary), the CI jobs with what each runs on, and how the project was read.
- **Results**: every check, grouped by category and filterable by status or text, each with why it matters and
  its result in each place (language and unit), with the tools found.
- **Matrix**: the checks by language and unit, each cell linking to its result.
- **Facts**: every fact the validator extracted, by kind, searchable, each origin linking to the file on the web when
  the project is a checkout with a known remote.
- **Run**: the validator's version, the options and the time each stage took.

Everything the project supplies is escaped; the facts travel as JSON in a script element and are rendered by the
page's own script.
"""

from __future__ import annotations

import html
import inspect
import json
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from project_validator.analysis import Analysis, file_url
from project_validator.core import Placed, Status
from project_validator.explanations import why
from project_validator.facts import as_dict
from project_validator.facts.jobs import Job
from project_validator.runner import Report
from project_validator.score import LEVEL_NAMES, Score
from project_validator.views.common import (
    OUTCOMES,
    STATUS_ORDER,
    SYMBOLS,
    branch_label,
    ci_summary,
    counts,
    credit,
    dedupe,
    ecosystems,
    fact_kinds,
    grouped,
    is_skipped,
    judged_places,
    place_label,
    reading,
    role_judgement,
    role_line,
    summary,
    units,
    unrecognised,
)
from project_validator.views.theme import STYLESHEET, THEME_SCRIPT, asset

UNIT_HEADERS = ("Directory", "Role", "Built with", "Languages and formats")
JOB_HEADERS = ("Job", "OS", "Compilers", "Toolchains", "Builds", "Configurations")
SECTIONS = (
    ("overview", "Overview"),
    ("detected", "Detected"),
    ("results", "Results"),
    ("matrix", "Matrix"),
    ("next", "Next steps"),
    ("facts", "Facts"),
    ("run", "Run"),
)


def e(value: object) -> str:
    """`value` as HTML text."""
    return html.escape(str(value), quote=True)


def _anchor(name: str) -> str:
    return "check-" + "".join(character if character.isalnum() else "-" for character in name)


def _pill(status: Status) -> str:
    return f'<span class="pill s-{status}">{SYMBOLS[status]} {status}</span>'


def _ring(percent: float, label: str) -> str:
    radius, width = 52, 12
    circumference = 2 * math.pi * radius
    shown = min(percent, 100.0)
    offset = circumference * (1 - shown / 100)
    colour = "var(--pass)" if percent >= 100 else "var(--accent)" if percent >= 50 else "var(--warn)"
    return (
        f'<div class="ring" role="img" aria-label="{e(label)}"><svg viewBox="0 0 128 128">'
        f'<circle class="track" cx="64" cy="64" r="{radius}" fill="none" stroke-width="{width}"/>'
        f'<circle class="value" cx="64" cy="64" r="{radius}" fill="none" stroke="{colour}" stroke-width="{width}" '
        f'stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"/></svg>'
        f'<div class="label"><div><strong>{math.floor(round(percent, 6))}%</strong><span>score</span></div></div></div>'
    )


def _bar(percent: float) -> str:
    return f'<div class="bar"><span style="width:{max(0.0, min(percent, 100.0)):.1f}%"></span></div>'


# --- the sections


def _status_chips(analysis: Analysis) -> str:
    found = counts(analysis.reports)
    return "".join(
        f'<span class="chip s-{status}"><span class="dot"></span>{found[status]} {OUTCOMES[status]}</span>'
        for status in STATUS_ORDER
        if found[status]
    )


def _score_chips(scored: Score) -> str:
    chips = [
        f'<span class="chip level">Level {scored.level} · {e(LEVEL_NAMES[scored.level])}</span>',
        f'<span class="chip">{scored.gates} of {len(scored.cells)} gates in place</span>',
    ]
    if scored.extra:
        chips.append(f'<span class="chip">+{credit(scored.extra)} extra credit</span>')
    if scored.held:
        chips.append(f'<span class="chip">+{credit(scored.held)} extra credit held until 100%</span>')
    return "".join(chips)


def _commit(analysis: Analysis) -> str:
    """` · main @ 1a2b3c4d5e`, linked to the commit on the web when the remote is known."""
    git = analysis.git
    if not git.commit:
        return ""
    short = f"<code>{e(git.commit[:10])}</code>"
    linked = f'<a href="{e(f"{git.web}/commit/{git.commit}")}">{short}</a>' if git.web else short
    return f" · {e(branch_label(git))} @ {linked}"


def _hero(analysis: Analysis) -> str:
    scored = analysis.score
    ring = _ring(scored.percent, f"score {scored.percent:.0f} percent") if scored is not None else ""
    chips = (_score_chips(scored) if scored is not None else "") + _status_chips(analysis)
    return (
        f'<section class="hero wrap" id="overview"><div class="card">{ring}<div>'
        f"<h1>{e(analysis.name)}</h1>"
        f'<div class="where">{e(analysis.project)}{_commit(analysis)}</div>'
        f'<div class="chips">{chips}</div>'
        f'<p class="muted" style="margin:.8rem 0 0">{e(summary(analysis.reports))} · read {e(reading(analysis))}</p>'
        f"</div></div></section>"
    )


def _breakdown(scored: Score) -> str:
    rows = []
    for name, (filled, slots) in sorted(scored.breakdown().items()):
        percent = 100.0 * filled / slots if slots else 100.0
        rows.append(
            f"<div>{e(name or 'The whole project')}</div>{_bar(percent)}"
            f'<div class="muted" style="text-align:right">{math.floor(round(percent, 6))}%</div>'
        )
    return f'<div class="breakdown">{"".join(rows)}</div>'


def _top_steps(scored: Score) -> str:
    items = []
    for step in scored.next_steps[:5]:
        where = f" <span class=muted>({e(step.where)})</span>" if step.where else ""
        todo = f"<br><span class=muted>{e(step.hint or step.message)}</span>" if step.hint or step.message else ""
        items.append(
            f'<li><strong style="color:var(--pass)">+{step.points:.1f}</strong> <code>{e(step.check)}</code>'
            f"{where}{todo}</li>"
        )
    return (
        f'<ol style="padding-left:1.2rem;margin:0">{"".join(items)}</ol>' if items else "<p>Every gate is in place.</p>"
    )


SCORE_EXPLAINED = (
    "100% means every quality gate that applies to each part of the project is in place. Each check's result for a "
    "language in a unit is one slot: a pass fills it, a warning half; auxiliary code weighs half. Complementary "
    "tools (a second analyser, scanner or fuzzer) earn extra credit above 100%, once every gate is in place."
)


def _overview(analysis: Analysis) -> str:
    scored = analysis.score
    if scored is None:
        return ""
    return (
        '<div class="wrap grid two">'
        f'<div class="card"><h3>Gates in place, by language</h3>{_breakdown(scored)}'
        f'<p class="muted" style="font-size:.85rem;margin-bottom:0">{e(SCORE_EXPLAINED)}</p></div>'
        f'<div class="card"><h3>Next steps</h3>{_top_steps(scored)}'
        '<p style="margin-bottom:0"><a href="#next">All next steps →</a></p></div>'
        "</div>"
    )


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    head = "".join(f"<th>{e(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _languages_card(analysis: Analysis) -> str:
    rows = ((f"<strong>{e(label)}</strong>", e(signals)) for label, signals in ecosystems(analysis))
    found = unrecognised(analysis)
    extra = f'<p class="muted">Not recognised: {e(found)}</p>' if found else ""
    table = _table(("Language or format", "Recognised by"), rows)
    return f'<div class="card"><h3>Languages and formats</h3>{table}{extra}</div>'


def _units_card(analysis: Analysis) -> str:
    rows = (
        (f"<code>{e(directory)}</code>", e(role), e(systems), e(names))
        for directory, role, systems, names in units(analysis)
    )
    return f'<div class="card"><h3>Units</h3>{_table(UNIT_HEADERS, rows)}</div>'


ROLES_EXPLAINED = (
    "Every source outside vendored code is judged as the product, unless <code>--auxiliary</code> names it (by role, "
    "language or directory): auxiliary code weighs half in the score, is not asked for the product's own gates, and "
    "its failures are warnings."
)


def _roles_card(analysis: Analysis, vendored: Sequence[str]) -> str:
    rows = (
        (
            e(role_line(found).split(":", 1)[0]),
            e(", ".join(f"{d}/" if d != "." else "the root" for d in found.directories)),
            str(found.files),
            e(", ".join(found.languages) or "-"),
            e(role_judgement(found)),
        )
        for found in analysis.roles
    )
    more = f" and {len(vendored) - 8} more" if len(vendored) > 8 else ""
    listed = f'<p class="muted">Vendored (never judged): {e(", ".join(vendored[:8]) + more)}</p>' if vendored else ""
    return (
        f'<div class="card" style="margin-top:1rem"><h3>Code by role</h3>'
        f'<p class="muted" style="margin-top:0">{ROLES_EXPLAINED}</p>'
        f"{_table(('Role', 'Where', 'Files', 'Languages', 'Judged'), rows)}{listed}</div>"
    )


def _job_row(job: Job) -> tuple[str, ...]:
    def listed(values: Iterable[object]) -> str:
        return e(", ".join(sorted(map(str, values))) or "-")

    return (
        e(job.name),
        e(job.os or "-"),
        listed(job.compilers),
        listed(job.toolchains),
        listed(job.ecosystems),
        listed(job.configurations),
    )


def _ci_card(analysis: Analysis, jobs: Sequence[Job]) -> str:
    return (
        f'<div class="card" style="margin-top:1rem"><h3>CI <span class="muted" style="font-weight:400">'
        f"{e(ci_summary(analysis))}</span></h3>{_jobs([_job_row(job) for job in jobs], len(jobs))}</div>"
    )


def _detected(analysis: Analysis) -> str:
    structure = analysis.structure
    if structure is None:
        return (
            f'<section class="wrap" id="detected"><h2>Detected</h2><div class="card">'
            f"<p>The project could not be read: {e(analysis.error)}</p></div></section>"
        )
    return (
        '<section class="wrap" id="detected"><h2>What was detected</h2>'
        f'<div class="grid two">{_languages_card(analysis)}{_units_card(analysis)}</div>'
        f"{_roles_card(analysis, structure.vendored)}{_ci_card(analysis, structure.ci_jobs)}</section>"
    )


JOBS_SHOWN = 8  # CI jobs listed before the rest are folded away


def _jobs(rows: Iterable[Sequence[str]], count: int) -> str:
    rows = list(rows)
    if not rows:
        return ""
    shown = _table(JOB_HEADERS, rows[:JOBS_SHOWN])
    if count <= JOBS_SHOWN:
        return shown
    rest = _table(JOB_HEADERS, rows[JOBS_SHOWN:])
    return f'{shown}<details><summary class="muted">{count - JOBS_SHOWN} more jobs</summary>{rest}</details>'


def _places_table(analysis: Analysis, report: Report) -> str:
    places = judged_places(report) or [
        Placed(ecosystem="", unit="", result=report.result)  # a check of the whole project
    ]
    rows = []
    for place in places:
        details = dedupe(place.result.details)
        listed = "".join(f"<li>{e(detail)}</li>" for detail in details)
        tools = "".join(f'<span class="tool">{e(tool)}</span>' for tool in place.tools)
        rows.append(
            (
                e(place_label(place) or "the whole project"),
                _pill(place.result.status),
                e(place.result.message) + (f'<ul class="details">{listed}</ul>' if listed else ""),
                f'<span class="tools">{tools}</span>' if tools else '<span class="muted">-</span>',
            )
        )
    return f'<div class="places">{_table(("Where", "Status", "Result", "Tools"), rows)}</div>'


def _check(analysis: Analysis, report: Report) -> str:
    status = report.result.status
    reason = why(report.check.name)
    search = e(f"{report.check.name} {report.result.message} {' '.join(report.result.details)}".lower())
    why_html = f'<div class="why"><strong>Why it matters.</strong> {e(reason.why)}</div>' if reason else ""
    return (
        f'<details class="check s-{status}" id="{_anchor(report.check.name)}" data-status="{status}" '
        f'data-search="{search}">'
        f'<summary>{_pill(status)}<span class="name">{e(report.check.name)}</span>'
        f'<span class="message">{e(report.result.message)}</span></summary>'
        f'<div class="body">{why_html}'
        f'<p class="muted" style="margin-top:0">Looks for: {e(report.check.description)}</p>'
        f"{_places_table(analysis, report)}</div></details>"
    )


def _results(analysis: Analysis) -> str:
    found = counts(analysis.reports)
    filters = "".join(
        f'<button class="filter s-{status}" data-filter="{status}" '
        f'aria-pressed="{str(status is not Status.SKIP).lower()}">'
        f'<span class="dot"></span>{e(OUTCOMES[status])} {found[status]}</button>'
        for status in STATUS_ORDER
        if found[status]
    )
    groups = []
    for group in grouped(analysis.reports):
        tally = " · ".join(
            f"{group.counts[status]} {OUTCOMES[status]}" for status in STATUS_ORDER if group.counts[status]
        )
        checks = "".join(_check(analysis, report) for report in group.reports)
        groups.append(
            f'<div class="category"><h3>{e(group.category)} <span class="count">{e(tally)}</span></h3>{checks}</div>'
        )
    skipped = [report for report in analysis.reports if is_skipped(report)]
    if skipped:
        checks = "".join(_check(analysis, report) for report in skipped)
        groups.append(
            f'<div class="category" data-skipped><h3>Not applicable <span class="count">{len(skipped)}</span></h3>'
            f"{checks}</div>"
        )
    return (
        '<section class="wrap" id="results"><h2>Results</h2>'
        f'<div class="toolbar"><input type="search" id="result-search" placeholder="Filter the results…" '
        f'aria-label="Filter the results">{filters}</div>{"".join(groups)}</section>'
    )


def _matrix_columns(reports: Sequence[Report]) -> list[tuple[str, str]]:
    """Each (language, unit) a check judged, the root's first."""
    columns = {(place.ecosystem, place.unit): None for report in reports for place in report.result.places}
    return sorted(columns, key=lambda key: (key[1] != ".", key[1], key[0]))


def _matrix_cell(report: Report, place: Placed | None) -> str:
    if place is None or place.result.status is Status.SKIP:
        return '<td class="none">·</td>'
    status = place.result.status
    title = e(f"{report.check.name}, {place_label(place)}: {status}: {place.result.message}")
    return (
        f'<td class="cell s-{status}"><a href="#{_anchor(report.check.name)}" title="{title}">'
        f"{SYMBOLS[status]}</a></td>"
    )


def _matrix(analysis: Analysis) -> str:
    ordered = _matrix_columns(analysis.reports)
    if not ordered:
        return ""
    several_units = len({unit for _, unit in ordered}) > 1
    names = (f"{label} · {unit}" if several_units and unit not in (".", "") else label for label, unit in ordered)
    head = "".join(f'<th class="col"><span>{e(name)}</span></th>' for name in names)
    rows = []
    for report in analysis.reports:
        by_place = {(place.ecosystem, place.unit): place for place in report.result.places}
        if all(place.result.status is Status.SKIP for place in by_place.values()):
            continue  # no place, or none that it judged
        cells = "".join(_matrix_cell(report, by_place.get(key)) for key in ordered)
        rows.append(f'<tr><th class="row">{e(report.check.name)}</th>{cells}</tr>')
    return (
        '<section class="wrap" id="matrix"><h2>Matrix</h2><div class="card table-wrap">'
        f'<table class="matrix"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
        "</div></section>"
    )


def _next_steps(scored: Score | None) -> str:
    if scored is None:
        return ""
    if not scored.next_steps:
        return (
            '<section class="wrap" id="next"><h2>Next steps</h2><div class="card">'
            "<p>Every quality gate that applies is in place.</p></div></section>"
        )
    rows = (
        (
            f'<strong style="color:var(--pass)">+{step.points:.1f}</strong>',
            f'<a href="#{_anchor(step.check)}"><code>{e(step.check)}</code></a>'
            + (
                f'<br><span class="chip level">{"completes" if step.completes else "for"} '
                f"Level {step.needed_for}</span>"
                if step.needed_for
                else ""
            ),
            e(step.where or "the whole project"),
            _pill(step.status),
            e(step.message) + (f'<br><span class="muted">{e(step.hint)}</span>' if step.hint else ""),
        )
        for step in scored.next_steps
    )
    return (
        '<section class="wrap" id="next"><h2>Next steps</h2><div class="card">'
        '<p class="muted" style="margin-top:0">Each gate not yet in place, with the points filling it is worth; the '
        "next level's gates first.</p>"
        f"{_table(('Points', 'Gate', 'Where', 'Now', 'What was found'), rows)}</div></section>"
    )


def _fact_doc(kind: type) -> str:
    doc = inspect.getdoc(kind) or ""
    return doc.split("\n\n", 1)[0].replace("\n", " ")


def _facts_data(analysis: Analysis) -> str:
    kinds: dict[str, type] = {}
    rows = []
    for fact in analysis.facts.all:
        data = as_dict(fact)
        kind = str(data.pop("kind"))
        kinds.setdefault(kind, type(fact))
        origin = str(data.pop("origin", ""))
        rows.append({"k": kind, "o": origin, "u": file_url(analysis.git, origin), "f": data})
    documented = {kind: _fact_doc(found) for kind, found in kinds.items()}
    payload = {"facts": rows, "kinds": [[kind, n, documented.get(kind, "")] for kind, n in fact_kinds(analysis)]}
    # In a script element, "</" would end it early and "<!--" would change how it is parsed: no "<" is left in it.
    return json.dumps(payload, default=str, separators=(",", ":")).replace("<", "\\u003c")


def _facts(analysis: Analysis) -> str:
    return (
        '<section class="wrap" id="facts"><h2>Facts</h2>'
        '<p class="muted">Everything the validator read from the project, before judging it: the sources and build '
        "files, the CI jobs and the commands each runs, the tools' settings and runs. Each check's answer is built "
        "from these. Pick a kind, or search them all.</p>"
        '<div class="facts"><div class="card kinds" id="fact-kinds"></div>'
        '<div class="card"><div class="toolbar"><input type="search" id="fact-search" '
        'placeholder="Search the facts (a path, a tool, a value)…" aria-label="Search the facts"></div>'
        '<p class="fact-doc" id="fact-doc"></p><div id="fact-list"></div>'
        '<div class="pager"><button id="fact-prev">Previous</button><span class="muted" id="fact-page"></span>'
        '<button id="fact-next">Next</button></div></div></div>'
        f'<script type="application/json" id="facts-data">{_facts_data(analysis)}</script></section>'
    )


def _run(analysis: Analysis) -> str:
    total = sum(stage.seconds for stage in analysis.stages) or 1.0
    stages = "".join(
        f'<div class="stage"><div>{e(stage.name)}</div>{_bar(100.0 * stage.seconds / total)}'
        f'<div class="n">{stage.found:,} · {stage.seconds:.2f} s</div></div>'
        for stage in analysis.stages
    )
    options = "".join(
        f"<tr><td><code>{e(name)}</code></td><td>{e(value if value not in ([], None) else '-')}</td></tr>"
        for name, value in analysis.options.items()
    )
    return (
        '<section class="wrap" id="run"><h2>How it was read</h2><div class="grid two">'
        f'<div class="card"><h3>Extraction stages</h3><div class="stages">{stages}</div>'
        f'<p class="muted" style="margin-bottom:0">{e(reading(analysis))}; facts found by each stage.</p></div>'
        f'<div class="card"><h3>Run</h3><table><tbody>'
        f"<tr><td>Validator</td><td>project_validator {e(analysis.validator)}</td></tr>{options}"
        "</tbody></table></div></div></section>"
    )


SCRIPT = asset("report.js")


TOPBAR = (
    '<header class="topbar"><div class="wrap">'
    '<a class="brand" href="#overview"><span class="logo">pv</span>project_validator</a>'
    '<nav aria-label="Sections">{navigation}</nav>'
    '<button class="theme-toggle" type="button" aria-label="Switch between light and dark">Theme</button>'
    "</div></header>"
)


def render(analysis: Analysis, *, generated: datetime | None = None) -> str:
    """The HTML report of `analysis`, as one self-contained document."""
    when = (generated or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    navigation = "".join(f'<a href="#{anchor}">{e(label)}</a>' for anchor, label in SECTIONS)
    sections = (_hero, _overview, _detected, _results, _matrix, _facts, _run)
    body = "".join(section(analysis) for section in sections[:5]) + _next_steps(analysis.score)
    body += "".join(section(analysis) for section in sections[5:])
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(analysis.name)} · project_validator</title>\n"
        f"<style>\n{STYLESHEET}</style>\n<script>{THEME_SCRIPT}</script>\n</head>\n<body>\n"
        f"{TOPBAR.format(navigation=navigation)}\n<main>{body}</main>\n"
        f"<footer>Generated by project_validator {e(analysis.validator)} on {e(when)} in "
        f"{analysis.seconds:.2f} s.</footer>\n<script>{SCRIPT}</script>\n</body>\n</html>\n"
    )


__all__ = ["SECTIONS", "render"]
