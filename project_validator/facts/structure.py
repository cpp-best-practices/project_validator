"""Structure facts: the project's source files and their languages, its build files, and what its content shows.

The project map (`--map`, `project_validator.structure`) is a view over these facts.
"""

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems import Ecosystem, registered
from project_validator.facts import Fact, Facts, Origin

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
# Code the project carries but does not write: minified bundles, and the directories that hold other projects' code.
_MINIFIED = re.compile(r"[.-]min\.[^.]+$")
VENDOR_DIRECTORIES = frozenset({"vendor", "vendored", "third_party", "third-party", "thirdparty", "3rdparty"})


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFile(Fact):
    """A source file and its language (None for a file of an ecosystem that adds no language, such as a `.h` file of
    a C++ project). `ambiguous` files count once their ecosystem is recognised another way; `vendored` files (other
    projects' code, minified bundles) are recorded but make no language the project's."""

    language: str | None
    ambiguous: bool = False
    vendored: bool = False

    @property
    def path(self) -> str:
        return self.origin.path


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildFile(Fact):
    """A build file (or build directory, whose path ends in `/`) of a build system, and the languages it builds."""

    build_system: str
    languages: frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentLanguages(Fact):
    """Languages an ecosystem's probe found in the project's content, for intent that file names cannot show."""

    ecosystem: str
    languages: frozenset[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class UnrecognisedSuffix(Fact):
    """A suffix of source-like files no ecosystem accounts for, and how many files have it."""

    suffix: str
    files: int


def is_vendored(path: str) -> bool:
    posix = PurePosixPath(path)
    return bool(_MINIFIED.search(posix.name)) or bool(VENDOR_DIRECTORIES & set(posix.parts[:-1]))


def _build_files(project: Project, files: list[str]) -> Iterator[tuple[BuildFile | None, str]]:
    """For each project file that belongs to a build system: the build file it shows (None when already shown, as
    for the second file of a build directory), and the project file."""
    from project_validator.structure import build_files

    known, seen = build_files(), set()
    for path in files:
        for build_file, system in known.matches(path):
            if (build_file, system.name) in seen:
                yield None, path
                continue
            seen.add((build_file, system.name))
            declared: frozenset[str] = frozenset()
            if not build_file.endswith("/") and system.declared_languages:
                declared = system.declared_languages(project.read_text(path))
            languages = system.languages | declared
            yield BuildFile(origin=Origin(path=build_file), build_system=system.name, languages=languages), path


def _source_suffixes() -> dict[str, str]:
    return {
        suffix: language for ecosystem in registered() for suffix, language in (ecosystem.source_suffixes or {}).items()
    }


def _ambiguous(files: list[str], confirmed: list[Ecosystem]) -> Iterator[SourceFile]:
    for ecosystem in confirmed:
        for suffix, language in sorted((ecosystem.ambiguous_suffixes or {}).items()):
            for path in files:
                if PurePosixPath(path).suffix == suffix:
                    origin = Origin(path=path)
                    yield SourceFile(origin=origin, language=language, ambiguous=True, vendored=is_vendored(path))


def project_languages(facts: Facts) -> frozenset[str]:
    """The languages the project uses: those its build files build, its own sources are written in, or its content
    shows. Vendored code (other projects' code, minified bundles) adds none."""
    return frozenset(
        {
            *(language for build in facts.of(BuildFile) for language in build.languages),
            *(
                source.language
                for source in facts.of(SourceFile)
                if source.language is not None and not source.vendored
            ),
            *(language for content in facts.of(ContentLanguages) for language in content.languages),
        }
    )


def _sources(files: list[str]) -> Iterator[SourceFile]:
    known = _source_suffixes()
    for path in files:
        if (suffix := PurePosixPath(path).suffix) in known:
            yield SourceFile(origin=Origin(path=path), language=known[suffix], vendored=is_vendored(path))


def _content(project: Project) -> Iterator[ContentLanguages]:
    for ecosystem in registered():
        if ecosystem.detect is not None and (languages := ecosystem.detect(project) & ecosystem.languages):
            yield ContentLanguages(origin=Origin(path="."), ecosystem=ecosystem.label, languages=languages)


def _unrecognised(files: list[str], accounted: set[str], recognised: set[str]) -> Iterator[UnrecognisedSuffix]:
    """The suffixes of the source-like files no ecosystem accounts for, most common first."""
    counts = Counter(
        suffix
        for path in files
        if path not in accounted
        and (suffix := PurePosixPath(path).suffix)
        and suffix not in recognised
        and suffix.lower() not in NOT_SOURCE_SUFFIXES
        and not suffix.endswith("~")
    )
    for suffix, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        yield UnrecognisedSuffix(origin=Origin(path="."), suffix=suffix, files=count)


def structure_facts(project: Project) -> Iterator[Fact]:
    """The build files, the source files with their languages, what the content shows, the ambiguous sources of the
    ecosystems those show, and the unrecognised suffixes."""
    files = project.files()
    found = list(_build_files(project, files))
    plain = Facts((*(fact for fact, _ in found if fact is not None), *_sources(files), *_content(project)))
    yield from plain
    languages = project_languages(plain)
    ambiguous = list(_ambiguous(files, [ecosystem for ecosystem in registered() if ecosystem.languages & languages]))
    yield from ambiguous
    recognised = {PurePosixPath(source.path).suffix for source in (*plain.of(SourceFile), *ambiguous)}
    yield from _unrecognised(files, {path for _, path in found}, recognised)


__all__ = [
    "NOT_SOURCE_SUFFIXES",
    "VENDOR_DIRECTORIES",
    "BuildFile",
    "ContentLanguages",
    "SourceFile",
    "UnrecognisedSuffix",
    "is_vendored",
    "project_languages",
    "structure_facts",
]
