"""C/C++ compiler flags: the strict warning set and warnings as errors, for each compiler CI builds with, and security
hardening."""

import re
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from project_validator.core import Context, Result
from project_validator.ecosystems.model import C_FAMILY
from project_validator.evidence import existing_texts
from project_validator.facts import Facts
from project_validator.facts.build import CompilerOption
from project_validator.facts.practices import WARNINGS as WARNINGS_PRACTICE
from project_validator.facts.practices import WARNINGS_AS_ERRORS as WARNINGS_AS_ERRORS_PRACTICE
from project_validator.facts.practices import Evidence, Found, Practice, Requirement
from project_validator.rules import Hardening
from project_validator.text import Pattern, found_and_missing, matching_names
from project_validator.tools.toolchains import Flag, warning_flags, warnings_as_errors_flag

if TYPE_CHECKING:
    from project_validator.ci import Job

# The readers of the build files whose options the compiler flags are found among.
BUILD_FILES = ("CMake", "Meson")
PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
CLANG_COMPILERS = frozenset({"clang", "appleclang"})


def build_texts(context: Context) -> tuple[str, ...]:
    """Where C/C++ compiler flags are set: CMake files, CI configuration and CMake presets."""
    return (*context.cmake_texts, *context.ci_texts, *existing_texts(context, PRESET_FILES))


def _ci_compilers(context: Context) -> set[str]:
    return {compiler for job in context.ci_analysis.jobs for compiler in job.compilers}


# --- warnings and warnings as errors


def builds_c_or_cxx(job: Job) -> bool:
    """A job that names a compiler builds C/C++; one that only uses its runner's default compiler builds C/C++
    unless it is seen using another ecosystem's tools and not C/C++ build tools."""
    return not job.default_compiler or not job.ecosystems or "C/C++" in job.ecosystems


def ci_compilers(facts: Facts) -> tuple[str, ...]:
    """The compilers CI builds C/C++ with; GCC's flags are asked for when CI names none."""
    from project_validator.ci import Job

    found = {compiler for job in facts.of(Job) if builds_c_or_cxx(job) for compiler in job.compilers}
    return tuple(sorted(found)) or ("gcc",)


def _options(flag: Flag) -> Found:
    """The build files' options that set `flag` for C or C++ builds with the compiler judged."""

    def found(facts: Facts, compiler: str | None) -> Iterator[Evidence]:
        for option in facts.of(CompilerOption):
            applies = option.applies
            for_compiler = compiler is None or compiler in applies.allowed("compilers")
            if for_compiler and applies.allowed("languages") & C_FAMILY and flag.option.fullmatch(option.option):
                yield Evidence(option.origin.path, applies.requires)

    return found


# What a command that sets a flag, or a build system setting that passes it, holds.
_HINTS = ("-W", "/W", "-pedantic", "/permissive", "warning_level", "warnlevel", "werror", "WARNING_AS_ERROR")


def _flag(flag: Flag, *configured: str) -> Requirement:
    """A flag, on a command line or in the build files; `configured` are the build system settings a command line can
    set it with (`-Dwarning_level=3`)."""
    runs = re.compile("|".join((flag.standalone.pattern, *configured)))
    return Requirement(name=flag.name, runs=runs, found=_options(flag), hints=_HINTS)


# Meson's `warning_level` (and `--warnlevel`) on a command line, by the GCC flags it passes.
_LEVELS = {"-Wall": "[123]|everything", "-Wextra": "[23]|everything", "-Wpedantic": "3|everything"}


def _warnings(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    levels = (_LEVELS.get(flag.name) for flag in warning_flags(compiler or "gcc"))
    return tuple(
        _flag(flag, *([rf"(?:-Dwarning_level=|--warnlevel[=\s])(?:{level})\b"] if level else []))
        for flag, level in zip(warning_flags(compiler or "gcc"), levels, strict=True)
    )


_ERRORS_CONFIGURED = (
    r"(?<![\w-])--werror\b|-Dwerror=true\b",
    r"COMPILE_WARNING_AS_ERROR(?::BOOL)?=(?i:on|true|yes|1)\b",
)


def _errors(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    flag = warnings_as_errors_flag(compiler or "gcc")
    return () if flag is None else (_flag(flag, *_ERRORS_CONFIGURED),)


WARNINGS = Practice(
    name=WARNINGS_PRACTICE,
    languages=C_FAMILY,
    kind="compiler warning flags",
    requirements=_warnings,
    reads=BUILD_FILES,
    separator=" ",
    hint="enable -Wall -Wextra -Wpedantic -Wshadow -Wconversion (MSVC: /W4 /permissive-) for each compiler CI uses",
    compilers=ci_compilers,
)
WARNINGS_AS_ERRORS = Practice(
    name=WARNINGS_AS_ERRORS_PRACTICE,
    languages=C_FAMILY,
    kind="warnings as errors",
    requirements=_errors,
    any_one=True,
    reads=BUILD_FILES,
    searched="CI configuration or the build files (CMake files, presets, meson.build)",
    hint="add -Werror (GCC/Clang), /WX (MSVC) or set CMAKE_COMPILE_WARNING_AS_ERROR (Meson: werror=true), at least as "
    "an option",
    compilers=ci_compilers,
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
