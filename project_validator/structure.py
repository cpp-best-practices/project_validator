"""The map of a project (languages, build systems, CI) that checks are written against."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.core import Project
from project_validator.ecosystems import BUILD_SYSTEMS, ECOSYSTEMS

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, Job


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
        "toolchains": sorted(map(str, job.toolchains)),
        "configurations": sorted(map(str, job.configurations)),
    }


# Build file name -> the build system it belongs to.
BUILD_FILES = {name: system for system in BUILD_SYSTEMS for name in system.files}

# Source file suffix -> its language.
SOURCE_SUFFIXES = {
    suffix: language for ecosystem in ECOSYSTEMS for suffix, language in (ecosystem.source_suffixes or {}).items()
}


def _build_systems_and_languages(project: Project, files: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    """The build systems whose build files are present, and the languages they build or their build files declare."""
    build_files = [(path, BUILD_FILES[name]) for path in files if (name := PurePosixPath(path).name) in BUILD_FILES]
    build_systems = frozenset(system.name for _, system in build_files)
    languages = frozenset().union(
        *(system.languages for _, system in build_files),
        *(
            system.declared_languages(project.read_text(path))
            for path, system in build_files
            if system.declared_languages
        ),
    )
    return build_systems, languages


def _source_languages(files: list[str]) -> frozenset[str]:
    suffixes = {PurePosixPath(path).suffix for path in files}
    return frozenset(SOURCE_SUFFIXES[suffix] for suffix in suffixes if suffix in SOURCE_SUFFIXES)


def map_project(project: Project, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    files = project.files()
    build_systems, built_languages = _build_systems_and_languages(project, files)
    return ProjectStructure(
        languages=built_languages | _source_languages(files),
        build_systems=build_systems,
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
    )
