"""C/C++ compiler flags: the strict warning set, warnings as errors, and security hardening."""

import re
from collections.abc import Iterable

from project_validator.core import Context, Result
from project_validator.evidence import existing_texts
from project_validator.rules import Hardening, WarningPolicy, WarningsAsErrors
from project_validator.text import Pattern, found_and_missing, matching_names

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
CLANG_COMPILERS = frozenset({"clang", "appleclang"})


def build_texts(context: Context) -> tuple[str, ...]:
    """Where C/C++ compiler flags are set: CMake files, CI configuration and CMake presets."""
    return (*context.cmake_texts, *context.ci_texts, *existing_texts(context, PRESET_FILES))


def _ci_compilers(context: Context) -> set[str]:
    return {compiler for job in context.ci_analysis.jobs for compiler in job.compilers}


def _msvc_in_ci(context: Context) -> bool:
    return "msvc" in _ci_compilers(context)


# --- warnings


def _warning_flag(name: str, regex: str) -> Pattern:
    """Compiler flags are case-sensitive and must stand alone (`-Wshadow`, not `-Wshadow=local`)."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=-])"))


GCC_CLANG_WARNINGS = (
    _warning_flag("-Wall", r"-Wall"),
    _warning_flag("-Wextra", r"-Wextra"),
    _warning_flag("-Wpedantic", r"-Wpedantic|-pedantic(?:-errors)?"),
    _warning_flag("-Wshadow", r"-Wshadow"),
    _warning_flag("-Wconversion", r"-Wconversion"),
)

MSVC_WARNINGS = (
    _warning_flag("/W4", r"/W4|/Wall"),
    Pattern("/permissive-", re.compile(r"(?<![\w/-])/permissive-(?![\w=-])")),
)


def _required_warnings(context: Context) -> tuple[Pattern, ...]:
    return (*GCC_CLANG_WARNINGS, *MSVC_WARNINGS) if _msvc_in_ci(context) else GCC_CLANG_WARNINGS


WARNINGS = WarningPolicy(
    kind="compiler warning flags",
    recognised=(*GCC_CLANG_WARNINGS, *MSVC_WARNINGS),
    required=_required_warnings,
    texts=build_texts,
)

# --- warnings as errors

# Case-sensitive, as compiler flags and CMake variable names are.
# Partial or disabling forms such as `-Werror=<warning>`, `-Wno-error` and `/WX:NO` don't count.
WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        Pattern("-Werror", re.compile(r"(?<![\w=-])-Werror(?![\w=-])")),
        Pattern("/WX", re.compile(r"(?<![\w/:-])[/-]WX(?![\w:/-])")),
        Pattern(
            "COMPILE_WARNING_AS_ERROR",
            re.compile(
                r"(?:\b|(?<=-D))(?:CMAKE_)?COMPILE_WARNING_AS_ERROR\b(?::BOOL)?[\"']?\s*[=:\s]\s*"
                r"(?:\{[^}]*\"value\"\s*:\s*)?[\"']?(?i:ON|TRUE|YES|Y|1)\b"
            ),
        ),
    ),
    texts=build_texts,
    searched="CI configuration, CMake files or presets",
    hint="add -Werror (GCC/Clang), /WX (MSVC) or set CMAKE_COMPILE_WARNING_AS_ERROR, at least as an option",
)

# --- hardening


def _hardening_flag(name: str, regex: str) -> Pattern:
    """Flags must stand alone, so negated or disabled spellings (`-fcf-protection=none`, `/guard:cf-`) do not count."""
    return Pattern(name, re.compile(rf"(?<![\w/-])(?:{regex})(?![\w=:-])"))


def _define(name: str, regex: str) -> Pattern:
    """A preprocessor definition, as `-DNAME=value` or `add_compile_definitions(NAME=value)`, but not `-UNAME`."""
    return Pattern(name, re.compile(rf"(?:-D\s*|(?<![\w-]))(?:{regex})(?![\w=])"))


FHARDENED = _hardening_flag("-fhardened", r"-fhardened")

GCC_CLANG_HARDENING = (
    _define("_FORTIFY_SOURCE", r"_FORTIFY_SOURCE(?:=[1-9])?"),
    _hardening_flag("-fstack-protector-strong", r"-fstack-protector-(?:strong|all)"),
    _hardening_flag("-fcf-protection", r"-fcf-protection(?:=(?:full|branch|return|check))?"),
    _hardening_flag("-fstack-clash-protection", r"-fstack-clash-protection"),
    _define(
        "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE",
        r"_GLIBCXX_ASSERTIONS(?:=1)?|_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_(?:FAST|EXTENSIVE|DEBUG)",
    ),
)

MSVC_HARDENING = (
    _hardening_flag("/sdl", r"/sdl"),
    _hardening_flag("/guard:cf", r"/guard:cf"),
    _hardening_flag("/DYNAMICBASE", r"(?i:/DYNAMICBASE)"),
    _hardening_flag("/CETCOMPAT", r"(?i:/CETCOMPAT)"),
)


def _names(options: Iterable[Pattern]) -> str:
    return ", ".join(option.name for option in options)


def _hardening_failure(msvc_required: bool) -> str:
    message = f"no hardening options found; enable -fhardened (GCC 14+) or {_names(GCC_CLANG_HARDENING)}"
    return f"{message}, and for MSVC {_names(MSVC_HARDENING)}" if msvc_required else message


def _hardening(context: Context) -> Result:
    compilers = _ci_compilers(context)
    msvc_required = "msvc" in compilers
    texts = build_texts(context)

    if not matching_names(texts, (FHARDENED, *GCC_CLANG_HARDENING, *MSVC_HARDENING)):
        return Result.failed(_hardening_failure(msvc_required))

    fhardened = bool(matching_names(texts, (FHARDENED,)))
    found, missing = found_and_missing(texts, GCC_CLANG_HARDENING)
    msvc_found, msvc_missing = found_and_missing(texts, MSVC_HARDENING) if msvc_required else ([], [])
    enabled = ", ".join([*([FHARDENED.name] if fhardened else []), *found, *msvc_found])

    if fhardened and missing and compilers & CLANG_COMPILERS:
        return Result.warned(
            f"-fhardened is GCC-only; Clang in CI is missing hardening options: {', '.join([*missing, *msvc_missing])}",
            f"found {enabled}",
        )
    if missing := [*([] if fhardened else missing), *msvc_missing]:
        return Result.warned(f"missing hardening options: {', '.join(missing)}", f"found {enabled}")
    return Result.passed(f"hardening options are enabled: {enabled}")


HARDENING = Hardening(texts=build_texts, judge=_hardening)
