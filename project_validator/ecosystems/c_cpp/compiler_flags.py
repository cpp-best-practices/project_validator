"""C/C++ compiler flags: the strict warning set and warnings as errors, for each compiler CI builds with, and security
hardening."""

from __future__ import annotations

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts
from project_validator.facts.flags import errors_requirements, flag_requirements, warning_requirements
from project_validator.facts.jobs import Job
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording
from project_validator.tools.toolchains import (
    FHARDENED,
    GCC_HARDENING,
    MSVC_HARDENING,
    hardening_flags,
    warning_flags,
    warnings_as_errors_flag,
)

# The readers of the build files whose options the compiler flags are found among.
BUILD_FILES = ("CMake", "Meson")
PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")


# --- warnings and warnings as errors


def builds_c_or_cxx(job: Job) -> bool:
    """A job that names a compiler builds C/C++; one that only uses its runner's default compiler builds C/C++
    unless it is seen using another ecosystem's tools and not C/C++ build tools."""
    return not job.default_compiler or not job.ecosystems or "C/C++" in job.ecosystems


def ci_compilers(facts: Facts) -> tuple[str, ...]:
    """The compilers CI builds C/C++ with; GCC's flags are asked for when CI names none."""
    found = {compiler for job in facts.of(Job) if builds_c_or_cxx(job) for compiler in job.compilers}
    return tuple(sorted(found)) or ("gcc",)


def _warnings(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return warning_requirements(warning_flags(compiler or "gcc"), C_FAMILY)


def _errors(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return errors_requirements(warnings_as_errors_flag(compiler or "gcc"), C_FAMILY)


WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=C_FAMILY,
    requirements=_warnings,
    reads=BUILD_FILES,
    compilers=ci_compilers,
    words=Wording(
        kind="compiler warning flags",
        separator=" ",
        hint="enable -Wall -Wextra -Wpedantic -Wshadow -Wconversion (MSVC: /W4 /permissive-) for each compiler CI uses",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=C_FAMILY,
    requirements=_errors,
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

# --- hardening


def _hardening(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return flag_requirements(hardening_flags(compiler or "gcc"), C_FAMILY)


HARDENING = Practice(
    name=PracticeName.HARDENING,
    languages=C_FAMILY,
    requirements=_hardening,
    reads=BUILD_FILES,
    compilers=ci_compilers,
    words=Wording(
        kind="hardening options",
        hint=f"enable {FHARDENED} (GCC 14+) or {', '.join(flag.name for flag in GCC_HARDENING)}; for MSVC "
        f"{', '.join(flag.name for flag in MSVC_HARDENING)}",
    ),
)
