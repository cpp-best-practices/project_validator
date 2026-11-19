"""C and C++ compiler flags: the strict warning set and warnings as errors, for each compiler CI builds with, and
security hardening."""

from __future__ import annotations

from collections.abc import Callable

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts
from project_validator.facts.flags import errors_requirements, flag_requirements, warning_requirements
from project_validator.facts.jobs import Job
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording
from project_validator.tools.toolchains import (
    FHARDENED,
    GCC_HARDENING,
    MSVC_HARDENING,
    Flag,
    hardening_flags,
    warning_flags,
    warnings_as_errors_flag,
)

# The readers of the build files whose options the compiler flags are found among.
BUILD_FILES = ("CMake", "Meson")
PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")


# --- warnings and warnings as errors


def builds_c_or_cxx(job: Job) -> bool:
    """A job that names a compiler builds C or C++; one that only uses its runner's default compiler builds C or C++
    unless it is seen using another ecosystem's tools and not C or C++ build tools."""
    return not job.default_compiler or not job.ecosystems or bool(C_FAMILY & job.ecosystems)


def ci_compilers(facts: Facts) -> tuple[str, ...]:
    """The compilers CI builds C or C++ with; GCC's flags are asked for when CI names none."""
    found = {compiler for job in facts.of(Job) if builds_c_or_cxx(job) for compiler in job.compilers}
    return tuple(sorted(found)) or ("gcc",)


def _warnings(language: str) -> Callable[[Facts, str | None], tuple[Requirement, ...]]:
    return lambda _facts, compiler: warning_requirements(warning_flags(compiler or "gcc"), frozenset({language}))


def _errors(language: str) -> Callable[[Facts, str | None], tuple[Requirement, ...]]:
    return lambda _facts, compiler: errors_requirements(
        warnings_as_errors_flag(compiler or "gcc"), frozenset({language})
    )


def _warnings_practice(language: str) -> Practice:
    """The strict warning set, asked of `language`'s compilations alone: C++'s flags (`CMAKE_CXX_FLAGS`,
    `$<COMPILE_LANGUAGE:CXX>`) do not warn about C, nor C's about C++."""
    return Practice(
        name=PracticeName.WARNINGS,
        languages=frozenset({language}),
        requirements=_warnings(language),
        reads=BUILD_FILES,
        compilers=ci_compilers,
        words=Wording(
            kind="compiler warning flags",
            separator=" ",
            hint="enable -Wall -Wextra -Wpedantic -Wshadow -Wconversion (MSVC: /W4 /permissive-) for each compiler "
            "CI uses",
        ),
    )


def _errors_practice(language: str) -> Practice:
    return Practice(
        name=PracticeName.WARNINGS_AS_ERRORS,
        languages=frozenset({language}),
        requirements=_errors(language),
        any_one=True,
        reads=BUILD_FILES,
        compilers=ci_compilers,
        words=Wording(
            kind="warnings as errors",
            searched="CI configuration or the build files (CMake files, presets, meson.build)",
            hint="add -Werror (GCC/Clang), /WX (MSVC) or set CMAKE_COMPILE_WARNING_AS_ERROR (Meson: werror=true), "
            "at least as an option",
        ),
    )


C_WARNINGS, CXX_WARNINGS = _warnings_practice("C"), _warnings_practice("C++")
C_WARNINGS_AS_ERRORS, CXX_WARNINGS_AS_ERRORS = _errors_practice("C"), _errors_practice("C++")

# --- hardening

# The C++ standard library's assertions: hardening of C++ alone.
CXX_LIBRARY_HARDENING = frozenset({"_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE"})


def _hardening_flags(language: str, compiler: str) -> tuple[Flag, ...]:
    flags = hardening_flags(compiler)
    return flags if language == "C++" else tuple(flag for flag in flags if flag.name not in CXX_LIBRARY_HARDENING)


def _hardening(language: str) -> Callable[[Facts, str | None], tuple[Requirement, ...]]:
    return lambda _facts, compiler: flag_requirements(
        _hardening_flags(language, compiler or "gcc"), frozenset({language})
    )


def _hardening_practice(language: str) -> Practice:
    """Hardening, asked of `language`'s compilations: C is not asked for the C++ standard library's assertions."""
    gcc = [flag.name for flag in GCC_HARDENING if language == "C++" or flag.name not in CXX_LIBRARY_HARDENING]
    return Practice(
        name=PracticeName.HARDENING,
        languages=frozenset({language}),
        requirements=_hardening(language),
        reads=BUILD_FILES,
        compilers=ci_compilers,
        words=Wording(
            kind="hardening options",
            hint=f"enable {FHARDENED} (GCC 14+) or {', '.join(gcc)}; for MSVC "
            f"{', '.join(flag.name for flag in MSVC_HARDENING)}",
        ),
    )


C_HARDENING, CXX_HARDENING = _hardening_practice("C"), _hardening_practice("C++")
