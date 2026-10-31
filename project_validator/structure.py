"""The map of a project (languages, build systems, CI) that checks are written against."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.core import Project

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, Job

C_FAMILY = frozenset({"C", "C++"})

# Build file name -> (build system, the languages it builds).  CMake defaults to C and C++; Meson builds
# only the languages its project() declares, which are read separately.
BUILD_FILES = {
    "CMakeLists.txt": ("CMake", C_FAMILY),
    "meson.build": ("Meson", frozenset()),
    "Cargo.toml": ("Cargo", frozenset({"Rust"})),
    "pyproject.toml": ("Python packaging", frozenset({"Python"})),
    "setup.py": ("Python packaging", frozenset({"Python"})),
}

# `.h` is deliberately absent: it is used by both C and C++.
SOURCE_SUFFIXES = {
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    ".ixx": "C++",
    ".cppm": "C++",
    ".rs": "Rust",
    ".py": "Python",
}

# Meson language name -> language, for the languages a project() declaration can enable.
MESON_LANGUAGES = {"c": "C", "cpp": "C++", "rust": "Rust"}

_MESON_PROJECT = re.compile(r"\bproject\s*\(([^)]*)")
_MESON_KEYWORD_ARGUMENT = re.compile(r"\b\w+\s*:")
_MESON_STRING = re.compile(r"'([^']*)'")
_MESON_COMMENT = re.compile(r"#[^\n]*")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectStructure:
    languages: frozenset[str]
    build_systems: frozenset[str]
    ci_providers: tuple[str, ...]
    ci_files: tuple[str, ...]
    ci_jobs: tuple[Job, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "languages": sorted(self.languages),
            "build_systems": sorted(self.build_systems),
            "ci": {
                "providers": list(self.ci_providers),
                "files": list(self.ci_files),
                "jobs": [_job_as_dict(job) for job in self.ci_jobs],
            },
        }


def _job_as_dict(job: Job) -> dict[str, object]:
    return {
        "name": job.name,
        "os": job.os,
        "compilers": sorted(job.compilers),
        "configurations": sorted(map(str, job.configurations)),
    }


def _build_systems_and_languages(files: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    found = [BUILD_FILES[name] for name in {PurePosixPath(path).name for path in files} if name in BUILD_FILES]
    build_systems = frozenset(build_system for build_system, _ in found)
    languages = frozenset(language for _, built in found for language in built)
    return build_systems, languages


def _source_languages(files: list[str]) -> frozenset[str]:
    suffixes = {PurePosixPath(path).suffix for path in files}
    return frozenset(SOURCE_SUFFIXES[suffix] for suffix in suffixes if suffix in SOURCE_SUFFIXES)


def _meson_declared_languages(text: str) -> frozenset[str]:
    """The languages after the name in `project('name', 'c', ['cpp'], ...)`, before any keyword argument."""
    declaration = _MESON_PROJECT.search(_MESON_COMMENT.sub("", text))
    if declaration is None:
        return frozenset()
    positional = _MESON_KEYWORD_ARGUMENT.split(declaration.group(1), maxsplit=1)[0]
    declared = _MESON_STRING.findall(positional)[1:]
    return frozenset(MESON_LANGUAGES[name] for name in declared if name in MESON_LANGUAGES)


def _meson_languages(project: Project, files: list[str]) -> frozenset[str]:
    meson_files = (path for path in files if PurePosixPath(path).name == "meson.build")
    return frozenset().union(*(_meson_declared_languages(project.read_text(path)) for path in meson_files))


def map_project(project: Project, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    files = project.files()
    build_systems, built_languages = _build_systems_and_languages(files)
    return ProjectStructure(
        languages=built_languages | _meson_languages(project, files) | _source_languages(files),
        build_systems=build_systems,
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
    )
