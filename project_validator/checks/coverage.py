import re
from collections.abc import Callable
from dataclasses import dataclass

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of
from project_validator.text import Pattern, matching_names, pattern

PYTHON_SETTINGS_FILES = ("pyproject.toml", "setup.cfg", "tox.ini", ".coveragerc")


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageTools:
    """How an ecosystem reports branch coverage, and the path (or MC/DC) coverage that is a bonus on top of it."""

    searched: str
    texts: Callable[[Context], tuple[str, ...]]
    branch: tuple[Pattern, ...]
    path: tuple[Pattern, ...] = ()
    path_hint: str | None = None


def _ci_and_cmake_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *context.cmake_texts)


def _ci_and_python_settings_texts(context: Context) -> tuple[str, ...]:
    project = context.project
    return (*context.ci_texts, *(project.read_text(name) for name in PYTHON_SETTINGS_FILES if project.exists(name)))


def _ci_texts(context: Context) -> tuple[str, ...]:
    return context.ci_texts


C_AND_CXX_TOOLS = CoverageTools(
    searched="CI configuration or CMake files",
    texts=_ci_and_cmake_texts,
    branch=(
        pattern("gcovr", r"--txt-metric[\s=]+branch|--fail-under-branch|--branches\b"),
        pattern("lcov", r"\b(lcov_)?branch_coverage\s*=\s*1"),
        pattern("genhtml", r"--branch-coverage\b"),
        pattern("gcov", r"--branch-(probabilities|counts)\b"),
        pattern("llvm-cov", r"-show-branch(es|-summary)\b"),
    ),
    path=(
        pattern("gcc -fcondition-coverage", r"-fcondition-coverage\b"),
        pattern("gcc -fpath-coverage", r"-fpath-coverage\b"),
        pattern("gcov --prime-paths", r"--prime-paths\b"),
        pattern("clang MC/DC", r"-fcoverage-mcdc\b|-show-mcdc\b"),
    ),
    path_hint="consider adding path coverage (e.g. -fcondition-coverage or -fcoverage-mcdc)",
)

PYTHON_TOOLS = CoverageTools(
    searched="CI configuration or coverage.py settings",
    texts=_ci_and_python_settings_texts,
    branch=(
        pattern("coverage.py", r"\bcoverage\s+run\b[^\n]*--branch\b"),
        pattern("pytest-cov", r"--cov-branch\b"),
        Pattern(
            "coverage.py branch = true",
            re.compile(r"^\s*branch\s*=\s*(true|1|yes|on)\b", re.IGNORECASE | re.MULTILINE),
        ),
    ),
)

RUST_TOOLS = CoverageTools(
    searched="CI configuration",
    texts=_ci_texts,
    branch=(
        pattern("cargo-llvm-cov", r"\bcargo\s+(\+\S+\s+)?llvm-cov\b[^\n]*--branch\b"),
        pattern("cargo-tarpaulin", r"\bcargo\s+(\+\S+\s+)?tarpaulin\b[^\n]*(--branch\b|\s-b\b)"),
        pattern("grcov", r"\bgrcov\b[^\n]*--branch\b"),
    ),
    path=(
        pattern("cargo-llvm-cov MC/DC", r"\bllvm-cov\b[^\n]*--mcdc\b"),
        pattern("rustc MC/DC", r"-Z\s*coverage-options=\S*mcdc"),
    ),
    path_hint="consider adding MC/DC coverage (e.g. cargo llvm-cov --mcdc)",
)


def _reported_with(tools: CoverageTools, context: Context) -> Result:
    texts = tools.texts(context)
    branch_tools = matching_names(texts, tools.branch)
    if not branch_tools:
        return Result.failed(f"no branch coverage reporting found in {tools.searched}")

    message = f"branch coverage is reported with {', '.join(branch_tools)}"
    if path_tools := matching_names(texts, tools.path):
        return Result.passed(f"{message}; path coverage bonus: {', '.join(path_tools)}")
    return Result.passed(message, *([tools.path_hint] if tools.path_hint else []))


TOOLS = {C_AND_CXX: C_AND_CXX_TOOLS, PYTHON: PYTHON_TOOLS, RUST: RUST_TOOLS}


@check(
    name="coverage",
    description="CI reports branch coverage (path coverage is a bonus)",
    languages=languages_of(TOOLS),
)
def coverage(context: Context) -> Result:
    return check_each_ecosystem(context, TOOLS, _reported_with)
