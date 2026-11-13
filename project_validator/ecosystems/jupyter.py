"""Jupyter notebooks (`.ipynb`), a format: a notebook is JSON with `nbformat` and `cells`, which its parser checks
(`data-wellformed`). What is asked is that CI runs the notebooks as tests (`tests-run`: `pytest --nbmake` or
`--nbval`, `jupyter nbconvert --execute`, `jupyter execute`, papermill), formats them (`code-formatting`: `ruff format`,
which reads notebooks, or nbQA with black or ruff) and lints them (`static-analysis`: `ruff check`, or nbQA with ruff,
flake8 or pylint), and that `.ipynb_checkpoints/` is ignored (`vcs-ignore`) and never committed. Notebooks in a Python
project make it use both ecosystems. Whether notebooks are committed without their outputs (nbstripout) is a later
rule of `committed-artifacts`."""

from __future__ import annotations

import json
import re

from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, program, starts_with
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either, when
from project_validator.facts.wellformed import ParseError, Parser, decoded

JUPYTER = "Jupyter"
JUPYTER_ONLY = frozenset({JUPYTER})

JUPYTER_ECOSYSTEM = Ecosystem(
    label="Jupyter",
    kind="format",
    languages=JUPYTER_ONLY,
    source_suffixes={".ipynb": JUPYTER},
    ci_programs=(("jupyter",), ("papermill",), ("nbqa",), ("nbstripout",), ("nbconvert",)),
)


# --- Well-formedness: JSON with the notebook's keys -------------------------------------------------------------------


def _parse_notebook(_path: str, data: bytes) -> None:
    """A notebook is a JSON object with an integer `nbformat` and a list of `cells`."""
    try:
        notebook = json.loads(decoded(data))
    except json.JSONDecodeError as error:
        raise ParseError(error.msg, error.lineno, error.colno) from error
    if not isinstance(notebook, dict):
        raise ParseError("not a notebook: the document is not an object")
    if not isinstance(notebook.get("nbformat"), int):
        raise ParseError("not a notebook: no nbformat version")
    if not isinstance(notebook.get("cells"), list):
        raise ParseError("not a notebook: no cells")


NOTEBOOK_PARSER = Parser(format=JUPYTER, parse=_parse_notebook)


# --- The notebooks run as tests -------------------------------------------------------------------------------------

NOTEBOOKS = TestFiles(name="notebooks (*.ipynb)", languages=JUPYTER_ONLY, path=re.compile(r"\.ipynb$"))


def _runs_notebooks(command: Command, _facts: Facts) -> Run | None:
    """pytest with the nbmake or nbval plugin, `jupyter nbconvert --execute` or `jupyter execute`, or papermill."""
    argv = resolved(command)
    if program(argv) in ("pytest", "py.test"):
        return tested() if has_option(argv, "--nbmake", "--nbval", "--nbval-lax") else None
    if starts_with(argv, ("jupyter", "nbconvert")) is not None:
        return tested() if has_option(argv, "--execute") else None
    return tested() if starts_with(argv, ("jupyter", "execute"), ("papermill",)) is not None else None


NOTEBOOK_RUNS = test_runner(
    name="notebook execution",
    languages=JUPYTER_ONLY,
    how="pytest --nbmake notebooks (or --nbval, jupyter nbconvert --execute, papermill)",
    runs=_runs_notebooks,
    tests=tests_of(NOTEBOOKS.name),
)


# --- Formatting and linting: ruff reads notebooks; nbQA runs the other tools on their cells ---------------------------

RUFF_FORMAT = format_tool(
    name="ruff format",
    languages=JUPYTER_ONLY,
    can={Enforcement.CHECK: "ruff format --check notebooks", Enforcement.APPLY: "ruff format notebooks"},
    formats=either(
        flagged(("ruff", "format"), checks=("--check", "--diff", "--exit-non-zero-on-format")),
        flagged(("nbqa", "ruff", "format"), checks=("--check", "--diff")),
    ),
    style=defined_by(settings=("ruff",)),
    reads=("ruff",),
)
NBQA_BLACK = format_tool(
    name="nbqa black",
    languages=JUPYTER_ONLY,
    can={Enforcement.CHECK: "nbqa black --check notebooks", Enforcement.APPLY: "nbqa black notebooks"},
    formats=flagged(("nbqa", "black"), checks=("--check", "--diff")),
    style=defined_by(settings=("black",)),
)

_NBQA_LINTERS = frozenset({"ruff", "flake8", "pylint", "mypy"})


def _lints_notebooks(command: Command) -> bool:
    """`ruff check` (ruff reads notebooks), or nbQA running a linter on the cells (`nbqa ruff`, not `nbqa ruff
    format`)."""
    argv = resolved(command)
    if starts_with(argv, ("ruff", "check")) is not None:
        return True
    return (
        program(argv) == "nbqa" and argv[1:2] in {(tool,) for tool in _NBQA_LINTERS} and argv[1:3] != ("ruff", "format")
    )


RUFF_CHECK = analyzer(
    name="ruff check",
    languages=JUPYTER_ONLY,
    how="ruff check notebooks (or nbqa ruff, nbqa flake8, nbqa pylint)",
    analyses=when(_lints_notebooks, analysed),
    rules=defined_by(named=("ruff.toml", ".ruff.toml"), settings=("ruff",)),
    reads=("ruff",),
)


# --- Outputs ---------------------------------------------------------------------------------------------------------

CHECKPOINTS = BuildOutput(
    languages=JUPYTER_ONLY,
    name="Jupyter's checkpoints (.ipynb_checkpoints/)",
    globs=ignored_at_top_level(r"\.ipynb_checkpoints"),
    paths=directories(".ipynb_checkpoints"),
    hint="consider ignoring .ipynb_checkpoints/",
    artifacts=(".ipynb_checkpoints/",),
)
