import re
from collections.abc import Callable
from dataclasses import dataclass

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of
from project_validator.text import Pattern, matching_names, pattern

PYTHON_FORMATTER_SECTIONS = re.compile(r"^\s*\[tool\.(?:ruff|black)\b", re.MULTILINE)


@dataclass(frozen=True, slots=True, kw_only=True)
class Formatter:
    """Where an ecosystem's formatting style is defined, and the CI commands that enforce it.

    A formatter with a `default_style` defines the formatting even without a configuration file.
    """

    name: str
    config_file: Callable[[Context], str | None]
    runs: tuple[Pattern, ...]
    hint: str
    default_style: bool = False


def _first_existing(context: Context, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if context.project.exists(name)), None)


def _clang_format_file(context: Context) -> str | None:
    return _first_existing(context, (".clang-format", "_clang-format"))


def _python_formatter_file(context: Context) -> str | None:
    project = context.project
    if project.exists("pyproject.toml") and PYTHON_FORMATTER_SECTIONS.search(project.read_text("pyproject.toml")):
        return "pyproject.toml"
    return _first_existing(context, ("ruff.toml", ".ruff.toml"))


def _rustfmt_file(context: Context) -> str | None:
    return _first_existing(context, ("rustfmt.toml", ".rustfmt.toml"))


FORMATTERS = {
    C_AND_CXX: Formatter(
        name="clang-format",
        config_file=_clang_format_file,
        runs=(pattern("clang-format", r"(?<![\w.-])clang-format\b"),),
        hint="consider a CI job that checks formatting (clang-format --dry-run -Werror) or applies it automatically",
    ),
    PYTHON: Formatter(
        name="ruff format or black",
        config_file=_python_formatter_file,
        runs=(
            pattern("ruff format", r"\bruff\s+format\b"),
            pattern("black", r"(?<![\w.-])black\b[^\n]*\s--(?:check|diff)\b|\bpsf/black@"),
        ),
        hint="consider a CI job that runs ruff format --check (or black --check)",
        default_style=True,
    ),
    RUST: Formatter(
        name="rustfmt",
        config_file=_rustfmt_file,
        runs=(pattern("rustfmt", r"\bcargo\s+(?:\+\S+\s+)?fmt\b|(?<![\w.-])rustfmt\b(?!\.toml)"),),
        hint="consider a CI job that runs cargo fmt --check",
        default_style=True,
    ),
}


def _formatting_enforced(formatter: Formatter, context: Context) -> Result:
    config = formatter.config_file(context)
    tools = matching_names(context.ci_texts, formatter.runs)
    if tools and config is not None:
        return Result.passed(f"{config} is defined and CI runs {', '.join(tools)}")
    if tools and formatter.default_style:
        return Result.passed(f"CI enforces the {', '.join(tools)} style")
    if config is None:
        return Result.failed(f"no {formatter.name} configuration found; formatting is not defined", formatter.hint)
    return Result.warned(f"{config} is defined but CI does not run {formatter.name}", formatter.hint)


@check(
    name="code-formatting",
    description="Formatting is defined (e.g. .clang-format, ruff, rustfmt) and CI enforces it",
    languages=languages_of(FORMATTERS),
)
def code_formatting(context: Context) -> Result:
    return check_each_ecosystem(context, FORMATTERS, _formatting_enforced)
