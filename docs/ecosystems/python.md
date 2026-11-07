# Python

Recognised by `.py` sources, `pyproject.toml` or `setup.py`.

## `tests-run`

`test_*.py` / `*_test.py` files run by pytest, unittest, tox or nox.

## `coverage`

`coverage run --branch`, `--cov-branch` or `branch = true`.

## `platform-matrix`

The toolchains are Python versions.

## `compiler-warnings`

Warnings are errors: `-W error`, `PYTHONWARNINGS=error`, or pytest `filterwarnings = error`.

## `type-checking`

mypy, pyright or basedpyright, pyrefly, or ty. Strict mode is a bonus: `strict = true` in `[tool.mypy]` or a `[mypy]`
section, `mypy --strict`, or pyright's `typeCheckingMode` `strict`.

## `code-formatting`

ruff or black; they have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit.

## `static-analysis`

`ruff check`, pylint or flake8, in CI or as a pre-commit hook.

## `security-scanning`

bandit, or ruff's `S` rules.

## `dependency-management`

Dependencies declared in `pyproject.toml`, `setup.py` or requirements files are locked by a committed `uv.lock`,
`poetry.lock`, `pdm.lock`, `Pipfile.lock` or `pylock.toml`, or by requirements pinned with `--hash`.

## `dependency-audit`

pip-audit or safety.

## `license`

`[project] license` in `pyproject.toml`.

## `committed-artifacts`

`__pycache__/`, `*.py[co]`, `*.egg-info/`, a top-level `dist/` or `build/`.

## `vcs-ignore`

`__pycache__/` or `*.py[cod]`.
