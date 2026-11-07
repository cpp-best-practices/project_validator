"""The C and C++ compilers' flag vocabulary: the strict warning set and the flag that makes warnings errors, for the
compilers that take GCC's flags (GCC, Clang, Apple Clang, Intel) and for MSVC.

Build systems translate their own settings into these flags (CMake's `COMPILE_WARNING_AS_ERROR`, Meson's `werror`
and `warning_level`), and the C/C++ practices ask for them per compiler.
"""

import re
from dataclasses import dataclass

GCC_LIKE = frozenset({"gcc", "clang", "appleclang", "intel"})
MSVC = "msvc"


@dataclass(frozen=True, slots=True)
class Flag:
    """A compiler flag, `name`d as messages give it, and the spellings that set it (`-pedantic` sets `-Wpedantic`)."""

    name: str
    spellings: str

    @property
    def option(self) -> re.Pattern[str]:
        """The flag as a whole build-file option."""
        return re.compile(rf"(?:{self.spellings})")

    @property
    def standalone(self) -> re.Pattern[str]:
        """The flag in a command line, standing alone (`-Wshadow`, not `-Wshadow=local`; `-Werror`, not
        `-Werror=format`)."""
        return re.compile(rf"(?<![\w/:=-])(?:{self.spellings})(?![\w=:-])")


GCC_WARNINGS = (
    Flag("-Wall", "-Wall"),
    Flag("-Wextra", "-Wextra"),
    Flag("-Wpedantic", "-Wpedantic|-pedantic(?:-errors)?"),
    Flag("-Wshadow", "-Wshadow"),
    Flag("-Wconversion", "-Wconversion"),
)
MSVC_WARNINGS = (Flag("/W4", "/W4|/Wall"), Flag("/permissive-", "/permissive-"))
GCC_WARNINGS_AS_ERRORS = Flag("-Werror", "-Werror")
MSVC_WARNINGS_AS_ERRORS = Flag("/WX", "[/-]WX")


def warning_flags(compiler: str) -> tuple[Flag, ...]:
    """The strict warning set of `compiler`; none for a compiler whose flags are not known."""
    return MSVC_WARNINGS if compiler == MSVC else GCC_WARNINGS if compiler in GCC_LIKE else ()


def warnings_as_errors_flag(compiler: str) -> Flag | None:
    return MSVC_WARNINGS_AS_ERRORS if compiler == MSVC else GCC_WARNINGS_AS_ERRORS if compiler in GCC_LIKE else None


type ByCompiler = tuple[tuple[frozenset[str], tuple[str, ...]], ...]
"""Flags by the compilers that take them."""

# What a build system's warnings-as-errors setting passes each compiler.
WARNINGS_AS_ERRORS_BY_COMPILER: ByCompiler = (
    (GCC_LIKE, (GCC_WARNINGS_AS_ERRORS.name,)),
    (frozenset({MSVC}), (MSVC_WARNINGS_AS_ERRORS.name,)),
)

__all__ = [
    "GCC_LIKE",
    "GCC_WARNINGS",
    "MSVC",
    "MSVC_WARNINGS",
    "WARNINGS_AS_ERRORS_BY_COMPILER",
    "ByCompiler",
    "Flag",
    "warning_flags",
    "warnings_as_errors_flag",
]
