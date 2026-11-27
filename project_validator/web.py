"""What the browser page calls (upstream #127): the validator runs in the visitor's browser under Pyodide, on a folder
they pick (`web/`), and shows its HTML report. The page never asks the source-control host (it has no token, and the
folder no `origin`), and nothing is built: everything else is read as the command line reads it."""

from __future__ import annotations

import contextlib
import io

from project_validator.cli import main


def report(path: str, *arguments: str) -> tuple[int, str]:
    """Validate the project at `path` as `project_validator PATH --format html --offline` does, with any more
    `arguments`: the exit code and the HTML report ("" when there is none: a usage error)."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
        code = main([path, "--format", "html", "--offline", *arguments])
    return code, printed.getvalue()


__all__ = ["report"]
