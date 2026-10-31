"""Optional colored terminal output with rich; the plain text output is used when it is missing."""

import importlib
from collections import Counter
from collections.abc import Sequence
from types import ModuleType
from typing import Any, TextIO

from project_validator.core import Status
from project_validator.runner import Report


class PrettyError(Exception):
    pass


def _import_rich() -> ModuleType | None:
    try:
        importlib.import_module("rich.console")
        importlib.import_module("rich.text")
        return importlib.import_module("rich")
    except ImportError:
        return None


_rich = _import_rich()

_STYLES = {
    Status.PASS: "bold green",
    Status.WARN: "bold yellow",
    Status.FAIL: "bold red",
    Status.ERROR: "bold magenta",
}
_OUTCOMES = {Status.PASS: "passed", Status.WARN: "warned", Status.FAIL: "failed", Status.ERROR: "errored"}
_BADGE_WIDTH = max(len(status) for status in Status) + 2


def available() -> bool:
    return _rich is not None


def print_reports(reports: Sequence[Report], stream: TextIO) -> None:
    if _rich is None:
        raise PrettyError("rich is not available")
    text = _rich.text
    console = _rich.console.Console(file=stream, force_terminal=True, soft_wrap=True, highlight=False)
    name_width = max((len(report.check.name) for report in reports), default=0)
    for report in reports:
        console.print(_report_line(text, report, name_width))
        for detail in report.result.details:
            console.print(text.Text(f"{'':{_BADGE_WIDTH + 1}}{detail}", style="dim"))
    console.print()
    console.print(_summary(text, Counter(report.result.status for report in reports)))


def _report_line(text: ModuleType, report: Report, name_width: int) -> Any:
    status = report.result.status
    return text.Text.assemble(
        (f"{status:^{_BADGE_WIDTH}}", f"reverse {_STYLES[status]}"),
        " ",
        (f"{report.check.name:<{name_width}}", "bold"),
        "  ",
        report.result.message,
    )


def _summary(text: ModuleType, counts: Counter[Status]) -> Any:
    outcomes = [(f"{counts[status]} {_OUTCOMES[status]}", _STYLES[status]) for status in Status if counts[status]]
    if not outcomes:
        return text.Text("no checks were run", style="dim")
    return text.Text(", ").join(text.Text(outcome, style=style) for outcome, style in outcomes)
