"""The map of a project (languages, build systems, CI) that checks are written against."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from project_validator.core import Project
from project_validator.ecosystems import BuildSystem, build_systems, registered

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, Job


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectStructure:
    languages: frozenset[str]
    build_systems: frozenset[str]
    # Ecosystem label -> the signals that recognised it.
    recognised_by: Mapping[str, tuple[str, ...]]
    # (suffix, number of files) of the files no ecosystem accounts for, most common first.
    unrecognised_suffixes: tuple[tuple[str, int], ...]
    ci_providers: tuple[str, ...]
    ci_files: tuple[str, ...]
    ci_jobs: tuple[Job, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "languages": sorted(self.languages),
            "build_systems": sorted(self.build_systems),
            "ecosystems": {label: list(signals) for label, signals in self.recognised_by.items()},
            "unrecognised_suffixes": [
                {"suffix": suffix, "files": count} for suffix, count in self.unrecognised_suffixes
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


# Suffixes of files that are not source code of any language: documents, styles, media, archives, binaries and plain
# data or configuration. They, and editor backups (`main.cpp~`), are never reported as unrecognised.
NOT_SOURCE_SUFFIXES = frozenset(
    {
        *(".md", ".markdown", ".rst", ".txt", ".adoc", ".dox", ".pdf", ".html", ".htm"),
        *(".css", ".scss", ".sass", ".less", ".map"),
        *(".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".mp3", ".mp4", ".wav"),
        *(".ttf", ".otf", ".woff", ".woff2"),
        *(".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar", ".whl", ".jar"),
        *(".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj", ".lib", ".pdb", ".class", ".pyc"),
        *(".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".csv", ".tsv", ".lock", ".env"),
        *(".log", ".diff", ".patch", ".orig", ".bak", ".swp"),
        # Templates (config.h.in, MANIFEST.in) can belong to any language.
        ".in",
    }
)
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


def source_suffixes() -> dict[str, str]:
    """Source file suffix -> its language, for every registered ecosystem."""
    return {
        suffix: language for ecosystem in registered() for suffix, language in (ecosystem.source_suffixes or {}).items()
    }


@dataclass(slots=True)
class _Recognition:
    """What a project was recognised as so far, and the signals that showed it, per ecosystem."""

    languages: set[str] = field(default_factory=set)
    build_systems: set[str] = field(default_factory=set)
    signals: dict[str, dict[str, None]] = field(default_factory=dict)
    recognised_suffixes: set[str] = field(default_factory=set)

    def add(self, languages: Iterable[str], signal: str) -> None:
        languages = set(languages)
        self.languages |= languages
        for ecosystem in registered():
            if ecosystem.languages & languages:
                self.signals.setdefault(ecosystem.label, {})[signal] = None


def _recognise_build_files(project: Project, files: list[str], recognised: _Recognition) -> set[str]:
    """Recognise the build systems whose build files are present; the files that are build files are returned."""
    known = build_files()
    build_file_paths = set()
    for path in files:
        for build_file, system in known.matches(path):
            build_file_paths.add(path)
            recognised.build_systems.add(system.name)
            if build_file.endswith("/"):
                recognised.add(system.languages, f"build directory {PurePosixPath(build_file).name}")
                continue
            declared = system.declared_languages(project.read_text(path)) if system.declared_languages else frozenset()
            recognised.add(system.languages | declared, f"build file {PurePosixPath(path).name}")
    return build_file_paths


def _recognise_sources(files: list[str], recognised: _Recognition) -> None:
    known = source_suffixes()
    for suffix in sorted({PurePosixPath(path).suffix for path in files} & known.keys()):
        recognised.add((known[suffix],), f"{suffix} files")
        recognised.recognised_suffixes.add(suffix)


def _recognise_content(project: Project, recognised: _Recognition) -> None:
    for ecosystem in registered():
        if ecosystem.detect is not None and (languages := ecosystem.detect(project) & ecosystem.languages):
            recognised.add(languages, "content")


def _recognise_ambiguous_suffixes(files: list[str], recognised: _Recognition) -> None:
    """Count the ambiguous suffixes of the ecosystems already recognised another way."""
    present = {PurePosixPath(path).suffix for path in files}
    confirmed = [ecosystem for ecosystem in registered() if ecosystem.languages & recognised.languages]
    for ecosystem in confirmed:
        for suffix, language in sorted((ecosystem.ambiguous_suffixes or {}).items()):
            if suffix in present:
                recognised.recognised_suffixes.add(suffix)
                if language is not None:
                    recognised.add((language,), f"{suffix} files")


def _unrecognised_suffixes(
    files: list[str], build_file_paths: set[str], recognised: _Recognition
) -> list[tuple[str, int]]:
    """The suffixes of the files no ecosystem accounts for, most common first."""
    counts = Counter(
        suffix
        for path in files
        if path not in build_file_paths
        and (suffix := PurePosixPath(path).suffix)
        and suffix not in recognised.recognised_suffixes
        and suffix.lower() not in NOT_SOURCE_SUFFIXES
        and not suffix.endswith("~")
    )
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def map_project(project: Project, ci_files: tuple[CiFile, ...], analysis: CiAnalysis) -> ProjectStructure:
    files = project.files()
    recognised = _Recognition()
    build_file_paths = _recognise_build_files(project, files, recognised)
    _recognise_sources(files, recognised)
    _recognise_content(project, recognised)
    _recognise_ambiguous_suffixes(files, recognised)
    return ProjectStructure(
        languages=frozenset(recognised.languages),
        build_systems=frozenset(recognised.build_systems),
        recognised_by={label: tuple(signals) for label, signals in recognised.signals.items()},
        unrecognised_suffixes=tuple(_unrecognised_suffixes(files, build_file_paths, recognised)),
        ci_providers=tuple(dict.fromkeys(ci_file.provider.name for ci_file in ci_files)),
        ci_files=tuple(ci_file.path for ci_file in ci_files),
        ci_jobs=analysis.jobs,
    )
