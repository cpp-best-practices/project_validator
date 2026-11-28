"""The TUI (`--tui`, with textual: `pip install project_validator[tui]`): browse an analysis in the terminal.

While the project is read, each extraction stage is shown as it finishes. Then a tree on the left holds the
overview, what was detected, the results by category, the score's next steps and the facts by kind; the pane on the
right shows what is selected. `/` searches the facts, `q` quits.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from typing import TYPE_CHECKING

from project_validator.analysis import Analysis
from project_validator.core import Check, Context, Status
from project_validator.explanations import why
from project_validator.facts import as_dict
from project_validator.runner import Report
from project_validator.score import LEVEL_NAMES, floor_percent
from project_validator.views.common import (
    ABOUT_NOTE,
    ABOUT_TITLE,
    SYMBOLS,
    about_rows,
    ci_summary,
    dedupe,
    ecosystems,
    files_by_language,
    host_summary,
    judged_places,
    language_views,
    place_count,
    place_label,
    reading,
    role_judgement,
    role_line,
    score_parts,
    summary,
    units,
)
from project_validator.views.console import STYLES
from project_validator.views.progress import STAGE_NAMES
from project_validator.words import folder

if TYPE_CHECKING:
    from textual.app import App

FACTS_SHOWN = 500  # facts listed at once; the search narrows them


def available() -> bool:
    return importlib.util.find_spec("textual") is not None


def markup(text: object) -> str:
    """`text` safe in textual's markup."""
    return str(text).replace("[", r"\[")


def status_markup(status: Status) -> str:
    return f"[bold {STYLES[status]}]{SYMBOLS[status]}[/]"


# --- the pages, as markup


def overview(analysis: Analysis) -> str:
    lines = [f"[bold]{markup(analysis.name)}[/]  [dim]{markup(analysis.project)}[/]", ""]
    if analysis.score is not None:
        scored = analysis.score
        lines += [
            f"[bold]{floor_percent(scored.percent)}%[/]  Level {scored.level} {LEVEL_NAMES[scored.level]}",
            f"[dim]{markup(scored.summary())}[/]",
            "",
        ]
        parts = score_parts(scored)
        for heading, rows in parts:
            lines += [f"[bold]By {heading}[/]"] if len(parts) > 1 else []
            for name, percent, _, _ in rows:
                width = 24
                done = round(width * min(percent, 100) / 100)
                bar = f"[green]{'█' * done}[/][dim]{'░' * (width - done)}[/]"
                lines.append(f"  {markup(name):<22} {bar} {floor_percent(percent)}%")
        lines.append("")
    lines += [markup(summary(analysis.reports)), f"[dim]Read {markup(reading(analysis))}[/]"]
    return "\n".join(lines)


def detected(analysis: Analysis) -> str:
    if analysis.structure is None:
        return f"[bold red]The project could not be read:[/] {markup(analysis.error)}"
    lines = ["[bold]Languages and formats[/]"]
    lines += [f"  [cyan]{markup(label)}[/]: {markup(signals)}" for label, signals in ecosystems(analysis)]
    lines += ["", "[bold]Where the files are[/]"]
    lines += [
        f"  [cyan]{markup(name)}[/]: {markup(count)} in {markup(where)}"
        for name, count, where in files_by_language(analysis)
    ]
    lines += ["", "[bold]Units[/]"]
    lines += [
        f"  [cyan]{markup(directory)}[/] ({markup(role)}): built with {markup(systems)}; {markup(names)}"
        for directory, role, systems, names in units(analysis)
    ]
    lines += ["", "[bold]Code by role[/]"]
    lines += [f"  {markup(role_line(found))}\n    [dim]{markup(role_judgement(found))}[/]" for found in analysis.roles]
    lines += ["", f"[bold]CI[/]: {markup(ci_summary(analysis))}"]
    for job in analysis.structure.ci_jobs:
        what = ", ".join(sorted(job.compilers | {str(t) for t in job.toolchains})) or "-"
        lines.append(f"  {markup(job.name)} [dim]{markup(job.os or '-')} / {markup(what)}[/]")
    lines += ["", f"[bold]Host[/]: {markup(host_summary(analysis))}", *_about(analysis)]
    lines += ["", "[bold]How it was read[/]"]
    lines += [
        f"  {markup(STAGE_NAMES.get(stage.name, stage.name))}: {stage.found:,} facts, {stage.seconds:.2f} s"
        for stage in analysis.stages
    ]
    return "\n".join(lines)


def _about(analysis: Analysis) -> list[str]:
    """What is shown of the project without being judged; nothing when there is none."""
    if not (rows := about_rows(analysis)):
        return []
    title = f"[bold]{ABOUT_TITLE}[/] [dim]{ABOUT_NOTE}[/]"
    return ["", title, *(f"  [cyan]{markup(label)}[/]: {markup(text)}" for label, text in rows)]


def report_page(report: Report) -> str:
    status = report.result.status
    lines = [f"{status_markup(status)} [bold]{markup(report.check.name)}[/]  {markup(report.result.message)}", ""]
    if reason := why(report.check.name):
        lines += [f"[italic]{markup(reason.why)}[/]", ""]
    lines += [f"[dim]Looks for: {markup(report.check.description)}[/]", ""]
    places = judged_places(report)
    if not places:
        lines += [f"  [dim]{markup(detail)}[/]" for detail in dedupe(report.result.details)]
    for place in places:
        tools = f"  [dim]tools: {markup(', '.join(place.tools))}[/]" if place.tools else ""
        label = f"[cyan]{markup(place_label(place))}[/]"
        lines.append(f"{status_markup(place.result.status)} {label}: {markup(place.result.message)}{tools}")
        lines += [f"    [dim]{markup(detail)}[/]" for detail in dedupe(place.result.details)]
    return "\n".join(lines)


def next_steps(analysis: Analysis) -> str:
    if analysis.score is None or not analysis.score.next_steps:
        return "Every quality gate that applies is in place."
    lines = ["[bold]Next steps[/] [dim](the points each is worth)[/]", ""]
    for step in analysis.score.next_steps:
        lines.append(f"[bold green]+{step.points:5.1f}[/]  {markup(step.describe())}")
    return "\n".join(lines)


def language_page(analysis: Analysis, language: str) -> str:
    """One language's view (upstream #388): its files, the folders that hold them, and what each check says of it."""
    view = next((found for found in language_views(analysis) if found.language == language), None)
    if view is None:
        return f"No {markup(language)} files were found."
    lines = [f"[bold]{markup(view.language)}[/]  [dim]{markup(view.files)}[/]", ""]
    lines += [f"  {markup(folder(place.directory))} [dim]{markup(place_count(place))}[/]" for place in view.places]
    lines += ["", "[bold]What the checks say[/]"]
    said = [
        f"{status_markup(result.status)} {markup(result.check)}  {markup(result.message)}"
        f" [dim]{markup(result.place)}[/]"
        for result in view.results
    ]
    lines += said or ["[dim]no check judges it[/]"]
    return "\n".join(lines)


def facts_page(analysis: Analysis, kind: str | None, search: str = "") -> str:
    found = [fact for fact in analysis.facts.all if kind is None or type(fact).__name__ == kind]
    needle = search.lower()
    lines = []
    shown = 0
    for fact in found:
        data = as_dict(fact)
        text = str(data)
        if needle and needle not in text.lower():
            continue
        shown += 1
        if shown > FACTS_SHOWN:
            continue
        name, origin = data.pop("kind"), data.pop("origin", "")
        fields = ", ".join(f"{key}={value!r}" for key, value in data.items() if value not in (None, "", [], (), False))
        lines.append(f"[bold]{markup(name)}[/] [cyan]{markup(origin)}[/]\n  [dim]{markup(fields)}[/]")
    head = f"[bold]{markup(kind or 'All facts')}[/]: {shown:,} of {len(found):,}" + (
        f" matching [italic]{markup(search)}[/]" if search else ""
    )
    more = [f"[dim]… and {shown - FACTS_SHOWN:,} more; search to narrow them[/]"] if shown > FACTS_SHOWN else []
    return "\n".join([head, "", *lines, *more])


def build_app(context: Context, checks: Sequence[Check], every_check: Sequence[str]) -> App[int]:
    """The TUI's app: it analyses the project in a worker, then shows the analysis. Its return code is the CLI's."""
    from project_validator.views.tui_app import Validator

    return Validator(context, checks, every_check)


def run(context: Context, checks: Sequence[Check], every_check: Sequence[str]) -> int:
    """Run the TUI; its exit code is 0, or 2 when textual is missing."""
    if not available():
        import sys

        print("project_validator: error: --tui needs textual: pip install project_validator[tui]", file=sys.stderr)
        return 2
    return build_app(context, checks, every_check).run() or 0


__all__ = [
    "available",
    "build_app",
    "detected",
    "facts_page",
    "markup",
    "next_steps",
    "overview",
    "report_page",
    "run",
    "status_markup",
]
