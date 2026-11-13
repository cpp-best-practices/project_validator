"""The map of a project (languages, build systems, CI) that checks are written against."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.ecosystems import BuildSystem, build_systems, registered
from project_validator.facts import Facts
from project_validator.facts.jobs import Job
from project_validator.facts.structure import (
    BuildFile,
    ContentLanguages,
    SourceFile,
    Unit,
    UnrecognisedSuffix,
    project_formats,
    project_languages,
    source_signal,
)

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectStructure:
    languages: frozenset[str]
    # The formats (JSON, YAML) the project's own files are in: data, not programs, judged for hygiene only.
    formats: frozenset[str]
    build_systems: frozenset[str]
    # Ecosystem label -> the signals that recognised it.
    recognised_by: Mapping[str, tuple[str, ...]]
    # (suffix, number of files) of the files no ecosystem accounts for, most common first.
    unrecognised_suffixes: tuple[tuple[str, int], ...]
    # Source files of other projects (vendored, minified), which make no language the project's.
    vendored: tuple[str, ...]
    # Each unit of the project: one for most, several for a monorepo or a mixed-language project.
    units: tuple[Unit, ...]
    ci_providers: tuple[str, ...]
    ci_files: tuple[str, ...]
    ci_jobs: tuple[Job, ...]

    @property
    def languages_and_formats(self) -> frozenset[str]:
        """Every name a check may apply to: what the project's own files are written in, programs or data."""
        return self.languages | self.formats

    def as_dict(self) -> dict[str, object]:
        return {
            "languages": sorted(self.languages),
            "formats": sorted(self.formats),
            "build_systems": sorted(self.build_systems),
            "ecosystems": {label: list(signals) for label, signals in self.recognised_by.items()},
            "unrecognised_suffixes": [
                {"suffix": suffix, "files": count} for suffix, count in self.unrecognised_suffixes
            ],
            **({"vendored": list(self.vendored)} if self.vendored else {}),
            "units": [
                {
                    "directory": unit.directory,
                    "role": unit.role,
                    "build_systems": list(unit.build_systems),
                    "languages": sorted(unit.languages),
                    "formats": sorted(unit.formats),
                }
                for unit in self.units
            ],
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
        "ecosystems": sorted(job.ecosystems),
        "configurations": sorted(map(str, job.configurations)),
    }


_GLOB_CHARACTERS = frozenset("*?[")


@dataclass(frozen=True, slots=True)
class BuildFiles:
    """The build files of every registered build system: exact names, file name globs and directory name globs."""

    names: Mapping[str, BuildSystem]
    globs: tuple[tuple[str, BuildSystem], ...]
    directories: tuple[tuple[str, BuildSystem], ...]

    def matches(self, path: str) -> list[tuple[str, BuildSystem]]:
        """(the build file or directory, its build system) for each build system that `path` belongs to."""
        posix = PurePosixPath(path)
        found = [(path, system) for system in (self.names.get(posix.name),) if system is not None]
        found += [(path, system) for glob, system in self.globs if fnmatchcase(posix.name, glob)]
        parents = posix.parts[:-1]
        for depth, part in enumerate(parents):
            directory = "/".join(parents[: depth + 1])
            found += [(directory + "/", system) for glob, system in self.directories if fnmatchcase(part, glob)]
        return found


def build_files() -> BuildFiles:
    entries = [(name, system) for system in build_systems() for name in system.files]
    return BuildFiles(
        names={name: system for name, system in entries if not _GLOB_CHARACTERS & set(name)},
        globs=tuple(
            (name, system) for name, system in entries if _GLOB_CHARACTERS & set(name) and not name.endswith("/")
        ),
        directories=tuple((name[:-1], system) for name, system in entries if name.endswith("/")),
    )


def _found_signals(facts: Facts) -> Iterator[tuple[frozenset[str], str]]:
    """(languages, signal) in the order they recognise: build files, source suffixes, content, then the ambiguous
    suffixes that count once an ecosystem is recognised another way."""
    for build in facts.of(BuildFile):
        kind = "build directory" if build.origin.path.endswith("/") else "build file"
        yield build.languages, f"{kind} {PurePosixPath(build.origin.path).name}"
    # (suffix, language, ambiguous) of the project's own sources, in the order they were found.
    sources = dict.fromkeys(
        (source_signal(source.path), source.language, source.ambiguous)
        for source in facts.of(SourceFile)
        if source.language is not None and not source.vendored
    )
    for suffix, language in sorted((suffix, language) for suffix, language, ambiguous in sources if not ambiguous):
        yield frozenset({language}), f"{suffix} files"
    yield from ((content.languages, "content") for content in facts.of(ContentLanguages))
    yield from ((frozenset({language}), f"{suffix} files") for suffix, language, ambiguous in sources if ambiguous)


def _signals(facts: Facts) -> dict[str, tuple[str, ...]]:
    """Ecosystem label -> the signals that recognised it."""
    signals: dict[str, dict[str, None]] = {}
    for languages, signal in _found_signals(facts):
        for ecosystem in registered():
            if ecosystem.languages & languages:
                signals.setdefault(ecosystem.label, {})[signal] = None
    return {label: tuple(found) for label, found in signals.items()}


def map_project(facts: Facts, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    """The project map: a view over the structure facts, and the CI the facts show."""
    vendored = [source.path for source in facts.of(SourceFile) if source.vendored]
    return ProjectStructure(
        languages=project_languages(facts),
        formats=project_formats(facts),
        build_systems=frozenset(build.build_system for build in facts.of(BuildFile)),
        recognised_by=_signals(facts),
        unrecognised_suffixes=tuple((found.suffix, found.files) for found in facts.of(UnrecognisedSuffix)),
        vendored=tuple(vendored),
        units=facts.of(Unit),
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
    )
