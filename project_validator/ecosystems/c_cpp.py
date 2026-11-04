"""C and C++: built with CMake or Meson, judged by their compilers."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from project_validator.ecosystems.model import C_FAMILY, BuildSystem, Ecosystem, ToolchainAxis

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
    axis=ToolchainAxis(noun="compiler", of_job=_compilers, runner_default=_uses_runner_default_compiler),
)
