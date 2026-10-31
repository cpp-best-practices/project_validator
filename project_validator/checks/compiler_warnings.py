import re
from collections.abc import Iterable

from project_validator.core import Context, Result, check
from project_validator.text import Pattern, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")


def _flag(name: str, regex: str) -> Pattern:
    """Compiler flags are case-sensitive and must stand alone (`-Wshadow`, not `-Wshadow=local`)."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=-])"))


GCC_CLANG_FLAGS = (
    _flag("-Wall", r"-Wall"),
    _flag("-Wextra", r"-Wextra"),
    _flag("-Wpedantic", r"-Wpedantic|-pedantic(?:-errors)?"),
    _flag("-Wshadow", r"-Wshadow"),
    _flag("-Wconversion", r"-Wconversion"),
)

MSVC_FLAGS = (
    _flag("/W4", r"/W4|/Wall"),
    Pattern("/permissive-", re.compile(r"(?<![\w/-])/permissive-(?![\w=-])")),
)


def _found_and_missing(texts: tuple[str, ...], flags: Iterable[Pattern]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for flag in flags:
        (found if any(flag.regex.search(text) for text in texts) else missing).append(flag.name)
    return found, missing


def _msvc_in_ci(context: Context) -> bool:
    return any("msvc" in job.compilers for job in context.ci_analysis.jobs)


def _preset_texts(context: Context) -> tuple[str, ...]:
    return tuple(context.project.read_text(name) for name in PRESET_FILES if context.project.exists(name))


@check(name="compiler-warnings", description="A strict compiler warning set is enabled")
def compiler_warnings(context: Context) -> Result:
    required = (*GCC_CLANG_FLAGS, *MSVC_FLAGS) if _msvc_in_ci(context) else GCC_CLANG_FLAGS
    texts = (*context.cmake_texts, *context.ci_texts, *_preset_texts(context))
    found, missing = _found_and_missing(texts, required)

    if not matching_names(texts, (*GCC_CLANG_FLAGS, *MSVC_FLAGS)):
        return Result.failed(f"no compiler warning flags found; enable at least {' '.join(f.name for f in required)}")
    if missing:
        return Result.warned(f"missing compiler warning flags: {', '.join(missing)}", f"found {' '.join(found)}")
    return Result.passed(f"strict compiler warnings are enabled: {' '.join(found)}")
