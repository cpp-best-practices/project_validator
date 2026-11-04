"""C and C++: built with CMake or Meson, judged by their compilers.

Rules that depend on the build system are in the `cmake` and `meson` modules; a project with neither is judged as a
CMake project.
"""

from typing import TYPE_CHECKING

from project_validator.core import Context
from project_validator.ecosystems.c_cpp.clang_tidy import FUNCTION_LIMITS
from project_validator.ecosystems.c_cpp.cmake import CMAKE
from project_validator.ecosystems.c_cpp.compiler_flags import HARDENING, WARNINGS, WARNINGS_AS_ERRORS
from project_validator.ecosystems.c_cpp.meson import MESON
from project_validator.ecosystems.model import C_FAMILY, Ecosystem, ToolchainAxis
from project_validator.evidence import first_existing
from project_validator.rules import (
    BuildOutputs,
    BuildTypes,
    CoverageTools,
    Formatter,
    directories,
    ignored_at_top_level,
)
from project_validator.text import pattern

if TYPE_CHECKING:
    from project_validator.ci import Job


def _compilers(job: Job) -> frozenset[str]:
    return job.compilers


def _uses_runner_default_compiler(job: Job) -> bool:
    return job.default_compiler


COMPILERS = ToolchainAxis(noun="compiler", of_job=_compilers, runner_default=_uses_runner_default_compiler)


def _clang_format_file(context: Context) -> str | None:
    return first_existing(context, (".clang-format", "_clang-format"))


CLANG_FORMAT = Formatter(
    name="clang-format",
    config_file=_clang_format_file,
    runs=(pattern("clang-format", r"(?<![\w.-])clang-format\b"),),
    hint="consider a CI job that checks formatting (clang-format --dry-run -Werror) or applies it automatically",
)


def _ci_and_cmake_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *context.cmake_texts)


COVERAGE = CoverageTools(
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

BUILD_DIRECTORY = BuildOutputs(
    name="the build directory",
    globs=ignored_at_top_level(r"(?:\[Bb\]uild|_?build|out|cmake-build)(?:[-_*][\w*-]*)?"),
    paths=directories("build", "out", "_build", "cmake-build-debug"),
    hint="consider ignoring the build directory (e.g. build/ and out/)",
)

# `.h` is deliberately absent: it is used by both C and C++.
C_AND_CXX = Ecosystem(
    label="C/C++",
    languages=C_FAMILY,
    build_systems=(CMAKE, MESON),
    default_build_system=CMAKE,
    source_suffixes={
        ".c": "C",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".hpp": "C++",
        ".hh": "C++",
        ".hxx": "C++",
        ".ixx": "C++",
        ".cppm": "C++",
    },
    rules=(
        COMPILERS,
        BuildTypes(axis=COMPILERS),
        CLANG_FORMAT,
        COVERAGE,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        HARDENING,
        FUNCTION_LIMITS,
        BUILD_DIRECTORY,
    ),
)
