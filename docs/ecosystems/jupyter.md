# Jupyter

A format, recognised by `.ipynb` notebooks. Notebooks in a Python project make it use both ecosystems; their results
are combined and labelled like any other mixed project's. A CI job works with the ecosystem when it runs `jupyter`,
`papermill`, `nbqa` or `nbstripout`.

## `data-wellformed`

Every notebook parses: JSON with an integer `nbformat` and a list of `cells`.

## `tests-run`

The notebooks run as tests: `pytest --nbmake` (or `--nbval`, `--nbval-lax`), `jupyter nbconvert --execute`,
`jupyter execute`, or papermill. The notebooks themselves are what defines the tests.

## `code-formatting`

`ruff format --check`, which reads notebooks, or nbQA running black or ruff on the cells (`nbqa black --check`,
`nbqa ruff format --check`); ruff's settings where the Python profile reads them (`ruff.toml`, `pyproject.toml`).

## `static-analysis`

`ruff check`, which lints notebooks, or nbQA running ruff, flake8, pylint or mypy on the cells.

## `vcs-ignore`

Jupyter's `.ipynb_checkpoints/` directories are ignored.

## `committed-artifacts`

A checkpoint is a build output, never committed.

## Not judged

Whether notebooks are committed without their outputs (nbstripout as a pre-commit hook or a git filter, or
`nbstripout --verify` in CI) is a later rule of `committed-artifacts` (#56). The other checks have no tool for
notebooks and are skipped.
