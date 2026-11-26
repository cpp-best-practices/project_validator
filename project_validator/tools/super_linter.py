"""super-linter (super-linter/super-linter, formerly github/super-linter, or its Docker image): one step that runs
many linters, each over the files of its kind, and fails on any finding (upstream #224). It is configured by
environment switches, `VALIDATE_<LINTER>`: with none set every linter runs; with any set to true only those run; with
only some set to false every other runs. `DISABLE_ERRORS=true` makes it only report.

Each linter is run as the command of the tool the validator knows it by (`LINTERS`), so the checks judge it as they
would that tool's own run; a linter no tool here knows is left out."""

from __future__ import annotations

import re
from collections.abc import Mapping

from project_validator.facts.expansion import ENVIRONMENT_INPUT, USES_INPUT, Action

# Each `VALIDATE_<switch>` and the command super-linter runs for it, as the tool that knows it is run (gitleaks and
# jscpd as secret-scanning and copy-paste-detection read them).
LINTERS: Mapping[str, tuple[str, ...]] = {
    "BASH": ("shellcheck",),
    "SHELL_SHFMT": ("shfmt", "-d"),
    "PYTHON_BLACK": ("black", "--check", "--diff"),
    "PYTHON_FLAKE8": ("flake8",),
    "PYTHON_PYLINT": ("pylint",),
    "PYTHON_MYPY": ("mypy",),
    "PYTHON_RUFF": ("ruff", "check"),
    "JAVASCRIPT_ES": ("eslint",),
    "TYPESCRIPT_ES": ("eslint",),
    "JAVASCRIPT_PRETTIER": ("prettier", "--check"),
    "TYPESCRIPT_PRETTIER": ("prettier", "--check"),
    "GO": ("golangci-lint", "run"),
    "DOCKERFILE_HADOLINT": ("hadolint",),
    "MARKDOWN": ("markdownlint",),
    "GITHUB_ACTIONS": ("actionlint",),
    "TERRAFORM_TFLINT": ("tflint",),
    "TERRAFORM_FMT": ("terraform", "fmt", "-check"),
    "RUBY": ("rubocop",),
    "CLANG_FORMAT": ("clang-format", "--dry-run", "--Werror"),
    "KOTLIN": ("ktlint",),
    "GOOGLE_JAVA_FORMAT": ("google-java-format", "--dry-run", "--set-exit-if-changed"),
    "LUA": ("luacheck",),
    "RUST_CLIPPY": ("cargo", "clippy"),
    "RUST_2021": ("rustfmt", "--check", "--edition", "2021"),
    "GITLEAKS": ("gitleaks", "detect"),
    "CHECKOV": ("checkov", "-d", "."),
    "JSCPD": ("jscpd",),
    "SQLFLUFF": ("sqlfluff", "lint"),
    "KUBERNETES_KUBECONFORM": ("kubeconform",),
    "PHP_PHPSTAN": ("phpstan", "analyse"),
    "PHP_PSALM": ("psalm",),
    "PHP_PHPCS": ("phpcs",),
    "ANSIBLE": ("ansible-lint",),
    "CLOJURE": ("clj-kondo", "--lint", "."),
    "DART": ("dart", "analyze"),
    "SCALAFMT": ("scalafmt", "--test"),
    "LATEX": ("chktex",),
}
# The linters super-linter 3 had (grafana/helm-charts' v3.12.0): the others came in later versions.
VERSION_3 = frozenset(
    {"BASH", "PYTHON_BLACK", "PYTHON_FLAKE8", "PYTHON_PYLINT", "JAVASCRIPT_ES", "TYPESCRIPT_ES", "GO"}
    | {"DOCKERFILE_HADOLINT", "MARKDOWN", "TERRAFORM_TFLINT", "RUBY", "KOTLIN", "LUA", "ANSIBLE", "CLOJURE"}
)
# The major version a `uses:` names by its tag (`@v3`, `@v3.17.1`, `:v3.12.0`, `:slim-v7`); a commit names none.
_MAJOR = re.compile(r"[@:](?:slim-)?v(\d+)(?:\.\d+)*$")
_SWITCH = f"{ENVIRONMENT_INPUT}VALIDATE_"
# Which files are linted (all, or those a change touches), not which linters run.
_WHOLE_CODEBASE = f"{_SWITCH}ALL_CODEBASE"


def _switches(inputs: Mapping[str, str]) -> dict[str, bool]:
    """Each `VALIDATE_<linter>` switch the environment sets, on or off."""
    return {
        name.removeprefix(_SWITCH): value.strip().lower() == "true"
        for name, value in inputs.items()
        if name.startswith(_SWITCH) and name != _WHOLE_CODEBASE and value.strip().lower() in ("true", "false")
    }


def _linters(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """The commands of the linters the switches leave on, of those the version has (every one, where its `uses:` names
    no version): every one, those switched on when any is, or every one but those switched off."""
    switches = _switches(inputs)
    on = {switch for switch, enabled in switches.items() if enabled}
    major = _MAJOR.search(inputs.get(USES_INPUT, ""))
    known = VERSION_3 if major and int(major[1]) <= 3 else LINTERS.keys()
    chosen = (switch for switch in LINTERS if switch in known and (switch in on if on else switches.get(switch, True)))
    return tuple(dict.fromkeys(LINTERS[switch] for switch in chosen))


def _disabled_errors(inputs: Mapping[str, str]) -> str:
    on = inputs.get(f"{ENVIRONMENT_INPUT}DISABLE_ERRORS", "").strip().lower() == "true"
    return "super-linter only reports with DISABLE_ERRORS" if on else ""


SUPER_LINTER_ACTIONS = tuple(
    Action(name=name, runs=_linters, environment=True, advisory=_disabled_errors)
    for name in (
        "super-linter/super-linter",
        "super-linter/super-linter/slim",
        "github/super-linter",
        "github/super-linter/slim",
        "docker://ghcr.io/super-linter/super-linter",
        "docker://ghcr.io/github/super-linter",
        "docker://github/super-linter",
    )
)
