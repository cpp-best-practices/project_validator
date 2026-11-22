"""The map of a project (languages, build systems, CI) that checks are written against."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
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
class Place:
    """A folder that holds some of a language's files: the deepest folder its files in one top-level folder and one
    role share ("." for the root)."""

    directory: str
    role: str
    files: int

    def as_dict(self) -> dict[str, object]:
        return {"directory": self.directory, "role": self.role, "files": self.files}


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageFiles:
    """Where a language's (or format's) files are: how many, their share of the project's own files, and the folders
    that hold them, most files first."""

    language: str
    files: int
    share: float
    places: tuple[Place, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "files": self.files,
            "share": round(self.share, 4),
            "places": [place.as_dict() for place in self.places],
        }


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
    # Where each language's and format's files are, most files first.
    files: tuple[LanguageFiles, ...] = ()

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
            "files": [found.as_dict() for found in self.files],
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


def _signals(facts: Facts, names: frozenset[str]) -> dict[str, tuple[str, ...]]:
    """Ecosystem label -> the signals that recognised it, for the ecosystems of the project's languages and formats
    (`names`): a CMake file that enables C and C++ by default does not make a C++ project a C one."""
    signals: dict[str, dict[str, None]] = {}
    for languages, signal in _found_signals(facts):
        for ecosystem in registered():
            if ecosystem.languages & languages & names:
                signals.setdefault(ecosystem.label, {})[signal] = None
    return {label: tuple(found) for label, found in signals.items()}


def _shared_directory(paths: list[str]) -> str:
    """The deepest folder every one of `paths` is in ("." for the root)."""
    parents = [PurePosixPath(path).parent.parts for path in paths]
    shared: list[str] = []
    for parts in zip(*parents, strict=False):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    return "/".join(shared) or "."


def language_files(sources: Iterable[SourceFile], names: frozenset[str]) -> tuple[LanguageFiles, ...]:
    """Where the files of each of `names` (the project's languages and formats) are: the project's own sources, by
    top-level folder and role, each placed in the deepest folder they share."""
    grouped: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(lambda: defaultdict(list))
    for source in sources:
        if source.language in names and not source.vendored:
            parts = PurePosixPath(source.path).parts
            top = parts[0] if len(parts) > 1 else "."
            grouped[source.language][top, source.role].append(source.path)
    total = sum(len(paths) for groups in grouped.values() for paths in groups.values())
    found = []
    for language, groups in grouped.items():
        places = sorted(
            (
                Place(directory=_shared_directory(paths), role=role, files=len(paths))
                for (_, role), paths in groups.items()
            ),
            key=lambda place: (-place.files, place.directory),
        )
        files = sum(place.files for place in places)
        found.append(LanguageFiles(language=language, files=files, share=files / total, places=tuple(places)))
    return tuple(sorted(found, key=lambda language: (-language.files, language.language)))


def map_project(facts: Facts, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    """The project map: a view over the structure facts, and the CI the facts show."""
    vendored = [source.path for source in facts.of(SourceFile) if source.vendored]
    languages, formats_ = project_languages(facts), project_formats(facts)
    return ProjectStructure(
        languages=languages,
        formats=formats_,
        build_systems=frozenset(build.build_system for build in facts.of(BuildFile)),
        recognised_by=_signals(facts, languages | formats_),
        unrecognised_suffixes=tuple((found.suffix, found.files) for found in facts.of(UnrecognisedSuffix)),
        vendored=tuple(vendored),
        units=facts.of(Unit),
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
        files=language_files(facts.of(SourceFile), languages | formats_),
    )
