"""C/C++ compiler flags: the strict warning set and warnings as errors, for each compiler CI builds with, and security
hardening."""

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts
from project_validator.facts.build import CompilerOption
from project_validator.facts.practices import HARDENING as HARDENING_PRACTICE
from project_validator.facts.practices import WARNINGS as WARNINGS_PRACTICE
from project_validator.facts.practices import WARNINGS_AS_ERRORS as WARNINGS_AS_ERRORS_PRACTICE
from project_validator.facts.practices import Evidence, Found, Practice, Requirement
from project_validator.tools.toolchains import (
    FHARDENED,
    GCC_HARDENING,
    MSVC_HARDENING,
    Flag,
    hardening_flags,
    warning_flags,
    warnings_as_errors_flag,
)

if TYPE_CHECKING:
    from project_validator.ci import Job

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


def _hardening(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return tuple(
        Requirement(name=flag.name, runs=flag.standalone, found=_options(flag), hints=flag.hints)
        for flag in hardening_flags(compiler or "gcc")
    )


HARDENING = Practice(
    name=HARDENING_PRACTICE,
    languages=C_FAMILY,
    kind="hardening options",
    requirements=_hardening,
    reads=BUILD_FILES,
    hint=f"enable {FHARDENED} (GCC 14+) or {', '.join(flag.name for flag in GCC_HARDENING)}; for MSVC "
    f"{', '.join(flag.name for flag in MSVC_HARDENING)}",
    compilers=ci_compilers,
)
