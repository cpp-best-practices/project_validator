"""Progress while the validator works, on a terminal's stderr (with rich): the extraction stage being read, then the
checks being run, so that a large project never looks like it hangs. The finished stages are listed as they end,
with what each found."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self, TextIO

from project_validator.core import Progress
from project_validator.views.console import ACCENT, available

STAGE_NAMES = {
    "the project's structure": "Finding the sources, build files and units",
    "the data files": "Parsing the data files and schemas",
    "the repository": "Reading what the repository tracks and ignores",
    "the test files": "Finding the tests",
    "the build probes": "Building the project (--build)",
    "the CI configuration": "Reading the CI configuration",
    "the CI commands": "Expanding what each CI job runs",
    "the CI jobs": "Working out what each CI job builds, and on what",
    "the settings": "Reading the tools' settings",
    "the tool runs": "Matching the tools CI runs",
}


class ProgressView:
    """A context manager that shows `Progress` events on `stream` while it is open (when rich is available)."""

    def __init__(self, stream: TextIO, *, transient: bool = True) -> None:
        self.stream, self.transient = stream, transient
        self._live: Any = None
        self._status: Any = None
        self._console: Any = None

    def __enter__(self) -> Self:
        if available():
            from rich.console import Console
            from rich.status import Status

            self._console = Console(file=self.stream, force_terminal=True, highlight=False)
            self._status = Status("Starting", console=self._console, spinner="dots", spinner_style=ACCENT)
            self._status.start()
        return self

    def __call__(self, event: Progress) -> None:
        if self._status is None:
            return
        if event.kind == "stage" and not event.done:
            self._status.update(f"[bold]{STAGE_NAMES.get(event.name, event.name)}[/]…")
        elif event.kind == "stage":
            self._console.print(
                f"[green]✔[/] {STAGE_NAMES.get(event.name, event.name)}"
                f" [dim]{event.found:,} facts, {event.seconds:.2f} s[/]",
                highlight=False,
            )
        elif event.kind == "check" and not event.done:
            self._status.update(f"[bold]Running the checks[/] [dim]{event.index}/{event.total}[/] {event.name}")

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        if self._status is not None:
            self._status.stop()


__all__ = ["STAGE_NAMES", "ProgressView"]
