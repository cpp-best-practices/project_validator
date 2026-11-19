"""The console report, with rich (`pip install project_validator[pretty]`): a header with the score, what was
detected and how it was read, the results grouped by category with each language's result on its own line, and the
score's breakdown and next steps. Skipped checks are counted, not listed, and long details are cut, unless
`verbose`.

rich is optional: `available()` says whether it is installed, and the CLI falls back to the plain text report.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, TextIO

from project_validator.analysis import Analysis
from project_validator.core import Status
from project_validator.runner import Report
from project_validator.score import LEVEL_NAMES, Score
from project_validator.views.common import (
    SYMBOLS,
    Group,
    branch_label,
    ci_summary,
    credit,
    dedupe,
    ecosystems,
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


class ConsoleError(Exception):
    pass


def _import_rich() -> dict[str, ModuleType] | None:
    try:
        return {
            name: importlib.import_module(f"rich.{name}")
            for name in ("console", "text", "table", "panel", "rule", "progress_bar", "padding", "box")
        }
    except ImportError:
        return None


_rich = _import_rich()

STYLES = {
    Status.PASS: "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.ERROR: "magenta",
    Status.SKIP: "bright_black",
}
DETAILS_SHOWN = 3  # details shown per result before they are cut, unless verbose
NEXT_STEPS = 8
ACCENT = "cyan"


def available() -> bool:
    return _rich is not None


def score_style(percent: float) -> str:
    if percent >= 100:
        return "bold green"
    if percent >= 75:
        return "green"
    if percent >= 50:
        return "yellow"
    return "red"


class _Renderer:
    def __init__(self, rich: dict[str, ModuleType], console: Any, *, verbose: bool) -> None:
        self.rich, self.console, self.verbose = rich, console, verbose
        self.text = rich["text"].Text

    def print(self, *renderables: Any) -> None:
        self.console.print(*renderables)

    def status(self, status: Status) -> Any:
        return self.text(SYMBOLS[status], style=f"bold {STYLES[status]}")

    def bar(self, percent: float, width: int = 30) -> Any:
        return self.rich["progress_bar"].ProgressBar(
            total=100, completed=min(percent, 100.0), width=width, complete_style=score_style(percent)
        )

    # --- the sections

    def header(self, analysis: Analysis) -> None:
        title = self.text.assemble(("project_validator ", "bold"), (analysis.validator, "dim"))
        top = self.text.assemble((analysis.name, f"bold {ACCENT}"), "  ", (str(analysis.project), "dim"))
        if analysis.git.commit:
            top.append(f"  {branch_label(analysis.git)} @ {analysis.git.commit[:10]}", style="dim")
        body: list[Any] = [top]
        if analysis.score is not None:
            body.append(self._score_line(analysis.score))
        body.append(self.text(summary(analysis.reports), style="dim"))
        group = self.rich["console"].Group(*body)
        self.print(self.rich["panel"].Panel(group, title=title, title_align="left", border_style=ACCENT))

    def _score_line(self, scored: Score) -> Any:
        table = self.rich["table"].Table.grid(padding=(0, 2))
        line = self.text.assemble(
            (f"{int(scored.percent)}%", score_style(scored.percent) + " bold"),
            "  ",
            (f"Level {scored.level} {LEVEL_NAMES[scored.level]}", "bold"),
        )
        gates = f"{scored.gates} of {len(scored.cells)} gates in place"
        if scored.extra:
            gates += f", +{credit(scored.extra)} extra credit"
        table.add_row(line, self.bar(scored.percent), self.text(gates, style="dim"))
        return table

    def table(self, *columns: str) -> Any:
        found = self.rich["table"].Table(box=self.rich["box"].SIMPLE_HEAD, show_edge=False, pad_edge=False)
        for column in columns:
            found.add_column(column)
        return found

    def detected(self, analysis: Analysis) -> None:
        self.print(self.rich["rule"].Rule("[bold]What was detected", align="left", style=ACCENT))
        if analysis.structure is None:
            self.print(self.text(f"The project could not be read: {analysis.error}", style="bold red"))
            return
        languages = self.table("Language or format", "Recognised by")
        for label, signals in ecosystems(analysis):
            languages.add_row(self.text(label, style=f"bold {ACCENT}"), signals)
        self.print(languages)
        found = self.table("Unit", "Role", "Built with", "Languages and formats")
        for directory, role, systems, names in units(analysis):
            found.add_row(directory if directory != "." else ". (the root)", role, systems, names)
        self.print(found)
        self.print(self.facts(analysis))
        if self.verbose:
            for stage in analysis.stages:
                self.print(self.text(f"    {stage.name}: {stage.found:,} facts in {stage.seconds:.3f} s", style="dim"))
        self.print()

    def facts(self, analysis: Analysis) -> Any:
        """The code in each role and how it is judged, what was not recognised, the CI and how much was read."""
        grid = self.rich["table"].Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, style="bold")
        grid.add_column(ratio=1)
        for found in analysis.roles:
            style = "yellow" if found.suggestion else "dim"
            label, _, where = role_line(found).partition(": ")
            grid.add_row(f"Code: {label}", self.text.assemble(where, "\n", (role_judgement(found), style)))
        if missing := unrecognised(analysis):
            grid.add_row("Not recognised", self.text(missing, style="dim"))
        grid.add_row("CI", ci_summary(analysis))
        grid.add_row("Read", reading(analysis))
        return grid

    def group(self, found: Group) -> None:
        counts = found.counts
        tally = "  ".join(f"{SYMBOLS[status]} {counts[status]}" for status in SYMBOLS if counts[status])
        self.print(self.rich["rule"].Rule(f"[bold]{found.category}[/]  [dim]{tally}[/]", align="left", style=ACCENT))
        grid = self.rich["table"].Table.grid(padding=(0, 1))
        grid.add_column(width=1)
        grid.add_column(width=1)
        grid.add_column(no_wrap=True, style="bold")
        grid.add_column(ratio=1)
        for report in found.reports:
            grid.add_row("", self.status(report.result.status), report.check.name, self.result(report))
        self.print(grid)
        self.print()

    def result(self, report: Report) -> Any:
        """A report's result: its message and details, or one line per place when it was judged in several."""
        places = judged_places(report)
        if len(places) <= 1:
            result = places[0].result if places else report.result
            return self.with_details(result.message, result.details)
        grid = self.rich["table"].Table.grid(padding=(0, 1))
        grid.add_column(width=1)
        grid.add_column(no_wrap=True, style=ACCENT)
        grid.add_column(ratio=1)
        for place in places:
            body = self.with_details(place.result.message, place.result.details)
            grid.add_row(self.status(place.result.status), place_label(place), body)
        return grid

    def with_details(self, message: str, details: tuple[str, ...]) -> Any:
        """The message, then its details (said once, and cut unless verbose), dimmed."""
        text = self.text(message)
        lines = dedupe(details)
        shown = lines if self.verbose else lines[:DETAILS_SHOWN]
        for detail in shown:
            text.append("\n" + detail, style="dim")
        if hidden := len(lines) - len(shown):
            text.append(f"\n… {hidden} more (--verbose shows them)", style="dim italic")
        return text

    def skipped(self, reports: tuple[Report, ...]) -> None:
        found = [report for report in reports if is_skipped(report)]
        if not found:
            return
        if self.verbose:
            self.print(self.rich["rule"].Rule("[bold]Not applicable", align="left", style="bright_black"))
            for report in found:
                self.print(self.text(f"  {SYMBOLS[Status.SKIP]} {report.check.name}: {report.result.message}", "dim"))
        else:
            names = ", ".join(report.check.name for report in found)
            self.print(self.text(f"{len(found)} checks do not apply here: {names} (--verbose says why)", "dim"))
        self.print()

    def score(self, scored: Score) -> None:
        self.print(self.rich["rule"].Rule("[bold]Score", align="left", style=ACCENT))
        self.print(self._score_line(scored))
        self.print(self.text(scored.summary(), style="dim"))
        breakdown = self.rich["table"].Table(box=None, show_header=False, pad_edge=False, padding=(0, 2))
        for name, (filled, slots) in sorted(scored.breakdown().items()):
            percent = 100.0 * filled / slots if slots else 100.0
            breakdown.add_row(
                self.text(name or "the whole project", style=ACCENT),
                self.bar(percent, 20),
                self.text(f"{int(percent)}%", style=score_style(percent)),
                self.text(f"{filled:g} of {slots:g} slots", style="dim"),
            )
        self.print(breakdown)
        if scored.next_steps:
            self.next_steps(scored)

    def next_steps(self, scored: Score) -> None:
        self.print()
        self.print(self.text("Next steps", style="bold"))
        steps = self.rich["table"].Table.grid(padding=(0, 2))
        steps.add_column(no_wrap=True, justify="right")
        steps.add_column(ratio=1)
        for step in scored.next_steps[: None if self.verbose else NEXT_STEPS]:
            head = self.text.assemble((step.check, "bold"))
            if step.where:
                head.append(f"  {step.where}", style=ACCENT)
            if step.needed_for:
                verb = "completes" if step.completes else "needed for"
                head.append(f"  {verb} Level {step.needed_for} {LEVEL_NAMES[step.needed_for]}", style="bold yellow")
            head.append("\n" + (step.hint or step.message), style="dim")
            steps.add_row(self.text(f"+{step.points:.1f}", style="bold green"), head)
        self.print(steps)
        if not self.verbose and len(scored.next_steps) > NEXT_STEPS:
            self.print(self.text(f"… {len(scored.next_steps) - NEXT_STEPS} more (--verbose)", "dim italic"))


def render(analysis: Analysis, stream: TextIO, *, verbose: bool = False, width: int | None = None) -> None:
    """Print the console report of `analysis` to `stream`."""
    if _rich is None:
        raise ConsoleError("rich is not available")
    console = _rich["console"].Console(file=stream, force_terminal=True, soft_wrap=False, highlight=False, width=width)
    renderer = _Renderer(_rich, console, verbose=verbose)
    renderer.header(analysis)
    renderer.detected(analysis)
    for found in grouped(analysis.reports):
        renderer.group(found)
    renderer.skipped(analysis.reports)
    if analysis.score is not None:
        renderer.score(analysis.score)


__all__ = ["ConsoleError", "available", "render"]
