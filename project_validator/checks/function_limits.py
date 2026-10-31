import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase

from project_validator import yaml_support
from project_validator.core import Context, Project, Result, check
from project_validator.text import matching_names, pattern

CLANG_TIDY_CONFIG = ".clang-tidy"
CLANG_TIDY_CHECK = "readability-function-size"
LENGTH_THRESHOLDS = ("LineThreshold", "StatementThreshold")

RUNS_CLANG_TIDY = pattern("clang-tidy", r"clang[-_]tidy")

# lizard options are case-sensitive (`-l` selects a language) and the default length limit of 1000 is no limit at all.
_LIZARD_LENGTH_LIMIT = re.compile(
    r"\blizard\b(?:\\\n|[^\n])*?(?<![\w-])"
    r"(?P<limit>(?:-L|--length|-T\s*(?:length|nloc)|--Threshold[\s=]+(?:length|nloc))[\s=]*\d+)"
)


@dataclass(frozen=True, slots=True)
class ClangTidyLimits:
    thresholds: tuple[str, ...] = ()
    problem: str | None = None


def lizard_limits(texts: Iterable[str]) -> list[str]:
    found = (
        f"lizard {' '.join(match['limit'].split())}" for text in texts for match in _LIZARD_LENGTH_LIMIT.finditer(text)
    )
    return list(dict.fromkeys(found))


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


@check(name="function-limits", description="Function length is limited by clang-tidy or lizard")
def function_limits(context: Context) -> Result:
    texts = (*context.ci_texts, *context.cmake_texts)
    if found := lizard_limits(texts):
        return Result.passed(f"function length is limited with {', '.join(found)}")

    clang_tidy = clang_tidy_limits(context.project)
    if clang_tidy.thresholds:
        tool = f"clang-tidy {CLANG_TIDY_CHECK} ({', '.join(clang_tidy.thresholds)})"
        if matching_names(texts, (RUNS_CLANG_TIDY,)):
            return Result.passed(f"function length is limited with {tool}")
        return Result.warned(
            f"function length limits are configured for {tool} but nothing runs clang-tidy",
            "run clang-tidy in CI, or set CMAKE_CXX_CLANG_TIDY",
        )

    details = (clang_tidy.problem,) if clang_tidy.problem else ()
    return Result.failed(
        f"function length is never limited; enable clang-tidy {CLANG_TIDY_CHECK} with a LineThreshold "
        "or run lizard -L in CI",
        *details,
    )
