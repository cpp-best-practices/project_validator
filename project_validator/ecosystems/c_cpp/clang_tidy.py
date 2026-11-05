"""clang-tidy's readability-function-size check, which limits C/C++ function length when clang-tidy runs."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase

from project_validator import yaml_support
from project_validator.core import Context, Project, Result
from project_validator.ecosystems.c_cpp.compiler_flags import build_texts
from project_validator.evidence import configuration
from project_validator.rules import SUGGESTED_LIZARD, Analyzer, FunctionLimits, StaticAnalysis
from project_validator.text import matching_names, pattern

CLANG_TIDY_CONFIG = ".clang-tidy"
CLANG_TIDY_CHECK = "readability-function-size"
LENGTH_THRESHOLDS = ("LineThreshold", "StatementThreshold")

RUNS_CLANG_TIDY = pattern("clang-tidy", r"clang[-_]tidy")


@dataclass(frozen=True, slots=True)
class ClangTidyLimits:
    thresholds: tuple[str, ...] = ()
    problem: str | None = None


def check_globs(checks: object) -> tuple[str, ...]:
    joined = ",".join(map(str, checks)) if isinstance(checks, list) else str(checks or "")
    return tuple(glob for glob in (part.strip() for part in joined.split(",")) if glob)


def is_enabled(name: str, globs: tuple[str, ...]) -> bool:
    """clang-tidy lets the last glob matching a check decide whether it is enabled."""
    decisions = (not glob.startswith("-") for glob in reversed(globs) if fnmatchcase(name, glob.removeprefix("-")))
    return next(decisions, False)


def check_options(options: object) -> Mapping[object, object]:
    if isinstance(options, list):
        return {option.get("key"): option.get("value") for option in options if isinstance(option, dict)}
    return options if isinstance(options, dict) else {}


def _is_positive(value: object) -> bool:
    text = str(value).strip()
    return text.isdigit() and int(text) > 0


def length_thresholds(options: Mapping[object, object]) -> tuple[str, ...]:
    return tuple(
        f"{name} {str(value).strip()}"
        for name in LENGTH_THRESHOLDS
        if _is_positive(value := options.get(f"{CLANG_TIDY_CHECK}.{name}"))
    )


def clang_tidy_limits(project: Project) -> ClangTidyLimits:
    if not project.exists(CLANG_TIDY_CONFIG):
        return ClangTidyLimits()
    try:
        config = yaml_support.load(project.read_text(CLANG_TIDY_CONFIG))
    except yaml_support.YamlError as error:
        return ClangTidyLimits(problem=f"{CLANG_TIDY_CONFIG} could not be read: {error}")
    config = config if isinstance(config, dict) else {}

    if not is_enabled(CLANG_TIDY_CHECK, check_globs(config.get("Checks"))):
        return ClangTidyLimits(problem=f"{CLANG_TIDY_CHECK} is not enabled by the Checks in {CLANG_TIDY_CONFIG}")
    if thresholds := length_thresholds(check_options(config.get("CheckOptions"))):
        return ClangTidyLimits(thresholds=thresholds)
    return ClangTidyLimits(
        problem=f"{CLANG_TIDY_CHECK} is enabled in {CLANG_TIDY_CONFIG} but sets no LineThreshold or StatementThreshold"
    )


def _clang_tidy_limits_enforced(context: Context) -> Result:
    clang_tidy = clang_tidy_limits(context.project)
    if clang_tidy.thresholds:
        tool = f"clang-tidy {CLANG_TIDY_CHECK} ({', '.join(clang_tidy.thresholds)})"
        if matching_names(build_texts(context), (RUNS_CLANG_TIDY,)):
            return Result.passed(f"function length is limited with {tool}")
        return Result.warned(
            f"function length limits are configured for {tool} but nothing runs clang-tidy",
            "run clang-tidy in CI, or set CMAKE_CXX_CLANG_TIDY",
        )

    details = (clang_tidy.problem,) if clang_tidy.problem else ()
    return Result.failed(
        f"function length is never limited; enable clang-tidy {CLANG_TIDY_CHECK} with a LineThreshold "
        f"or run {SUGGESTED_LIZARD} in CI",
        *details,
    )


FUNCTION_LIMITS = FunctionLimits(without_lizard=_clang_tidy_limits_enforced)


def _without_configuration(context: Context) -> str | None:
    if context.project.exists(CLANG_TIDY_CONFIG):
        return None
    return f"clang-tidy has no {CLANG_TIDY_CONFIG}, so it runs only its default checks"


# clang-tidy and cppcheck find different bugs, so both should run.
STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(
            name="clang-tidy",
            runs=RUNS_CLANG_TIDY.regex,
            configured=configuration((CLANG_TIDY_CONFIG,)),
            shortfall=_without_configuration,
        ),
        Analyzer(name="cppcheck", runs=re.compile(r"\bcppcheck\b|_CPPCHECK\b", re.IGNORECASE)),
    ),
    texts=build_texts,
    hint="consider running clang-tidy (CMAKE_CXX_CLANG_TIDY, checks chosen in a .clang-tidy) and cppcheck "
    "(CMAKE_CXX_CPPCHECK) in CI",
    all_required=True,
)
