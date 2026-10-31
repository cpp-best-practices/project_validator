"""The map of a project (languages, build systems, CI) that checks are written against."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.core import Project

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, Job

C_FAMILY = frozenset({"C", "C++"})

# Build file name -> (build system, the languages it builds).  CMake and Meson default to C and C++.
BUILD_FILES = {
    "CMakeLists.txt": ("CMake", C_FAMILY),
    "meson.build": ("Meson", C_FAMILY),
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


def map_project(project: Project, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    files = project.files()
    build_systems, built_languages = _build_systems_and_languages(files)
    return ProjectStructure(
        languages=built_languages | _source_languages(files),
        build_systems=build_systems,
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
    )
