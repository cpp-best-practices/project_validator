"""C and C++: built with CMake or Meson, judged by their compilers."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from project_validator.core import Context
from project_validator.ecosystems.model import C_FAMILY, BuildSystem, Ecosystem, ToolchainAxis
from project_validator.evidence import first_existing
from project_validator.rules import BuildTypes, CoverageTools, Formatter
from project_validator.text import pattern

if TYPE_CHECKING:
    from project_validator.ci import Job

# Meson language name -> language, for the languages a project() declaration can enable.
MESON_LANGUAGES = {"c": "C", "cpp": "C++", "rust": "Rust"}

_MESON_PROJECT = re.compile(r"\bproject\s*\(([^)]*)")
_MESON_KEYWORD_ARGUMENT = re.compile(r"\b\w+\s*:")
_MESON_STRING = re.compile(r"'([^']*)'")
_MESON_COMMENT = re.compile(r"#[^\n]*")


def meson_declared_languages(text: str) -> frozenset[str]:
    """The languages after the name in `project('name', 'c', ['cpp'], ...)`, before any keyword argument."""
    declaration = _MESON_PROJECT.search(_MESON_COMMENT.sub("", text))
    if declaration is None:
        return frozenset()
    positional = _MESON_KEYWORD_ARGUMENT.split(declaration.group(1), maxsplit=1)[0]
    declared = _MESON_STRING.findall(positional)[1:]
    return frozenset(MESON_LANGUAGES[name] for name in declared if name in MESON_LANGUAGES)


def is_cmake_build_tree(directory: Path) -> bool:
    return (directory / "CMakeCache.txt").is_file()


CMAKE = BuildSystem(name="CMake", files=("CMakeLists.txt",), languages=C_FAMILY, is_build_tree=is_cmake_build_tree)
# Meson builds only the languages its project() declares.
MESON = BuildSystem(name="Meson", files=("meson.build",), declared_languages=meson_declared_languages)


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

# `.h` is deliberately absent: it is used by both C and C++.
C_AND_CXX = Ecosystem(
    label="C/C++",
    languages=C_FAMILY,
    build_systems=(CMAKE, MESON),
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
    rules=(COMPILERS, BuildTypes(axis=COMPILERS), CLANG_FORMAT, COVERAGE),
)
