"""Structure facts: the project's source files and their languages, its build files, and what its content shows.

The project map (`--map`, `project_validator.structure`) is a view over these facts.
"""

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems import Ecosystem, build_systems, registered
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.roles import AUXILIARY, role
from project_validator.facts.tools import owner, within

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


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFile(Fact):
    """A source file, its language (None for a file of an ecosystem that adds no language, such as a `.h` file of a
    C++ project) and its `role` (see `role`). `ambiguous` files count once their ecosystem is recognised another
    way; vendored files (other projects' code, minified bundles) are recorded but make no language the project's."""

    language: str | None
    ambiguous: bool = False
    role: str = "product"

    @property
    def path(self) -> str:
        return self.origin.path

    @property
    def vendored(self) -> bool:
        return self.role == "vendored"


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
class Unit(Fact):
    """A unit of the project: a directory ("." for the root) that is built on its own, with its build systems and
    the languages of the sources in it (outside the units below it).

    A unit is the outermost directory with a build system's files (a CMake project's subdirectories, a Maven
    project's modules belong to it), or a member of a workspace a build file declares (npm workspaces, Cargo and uv
    workspaces, go.work). Sources outside every unit, and languages only content shows, belong to the root unit. A
    unit's languages are those of its own code: sources with an auxiliary role (docs, tooling, examples, benchmarks)
    count only in a unit with that role, and vendored code in none. A project with one unit is judged as before; a
    monorepo or a mixed-language project is judged unit by unit.
    """

    build_systems: tuple[str, ...]
    languages: frozenset[str]
    # What the unit is for, by its directory (see `role`): only `product` units are held to most practices.
    role: str = "product"

    @property
    def directory(self) -> str:
        return self.origin.path


@dataclass(frozen=True, slots=True, kw_only=True)
class UnrecognisedSuffix(Fact):
    """A suffix of source-like files no ecosystem accounts for, and how many files have it."""

    suffix: str
    files: int


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
                declared = system.declared_languages(path, project.read_text(path))
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
                    yield SourceFile(origin=origin, language=language, ambiguous=True, role=role(path))


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
            yield SourceFile(origin=Origin(path=path), language=known[suffix], role=role(path))


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


def _directory(build: BuildFile) -> str:
    """The directory a build file (or build directory, `App.xcodeproj/`) belongs to."""
    return str(PurePosixPath(build.origin.path.rstrip("/")).parent)


def _members(project: Project, build: BuildFile) -> list[str]:
    """The workspace member directories a build file declares, relative to the project."""
    system = next((found for found in build_systems() if found.name == build.build_system), None)
    if system is None or system.members is None or build.origin.path.endswith("/"):
        return []
    base = _directory(build)
    patterns = [
        str(PurePosixPath(base, pattern.removeprefix("./")))
        for pattern in system.members(project.read_text(build.origin.path))
    ]
    return [pattern.removeprefix("./") for pattern in patterns]


def _unit_roots(project: Project, builds: tuple[BuildFile, ...]) -> tuple[dict[str, list[str]], set[str]]:
    """Unit directory -> its build systems (each build system's outermost directories, and workspace members), and
    the directories of the build files that declare a workspace."""
    roots: dict[str, list[str]] = {}
    workspaces: set[str] = set()
    for system in dict.fromkeys(build.build_system for build in builds):
        own = [build for build in builds if build.build_system == system]
        directories = set(map(_directory, own))
        members = []
        for build in own:
            if declared := _members(project, build):
                workspaces.add(_directory(build))
                members += declared
        for directory in sorted(directories):
            declared_member = any(fnmatchcase(directory, pattern) for pattern in members)
            outer = not any(other != directory and within(directory, other) for other in directories)
            if declared_member or outer:
                roots.setdefault(directory, []).append(system)
    return roots, workspaces


def _units(project: Project, facts: Facts) -> Iterator[Unit]:
    roots, workspaces = _unit_roots(project, facts.of(BuildFile))
    languages: dict[str, set[str]] = {root: set() for root in roots}
    for source in facts.of(SourceFile):
        unit = owner(source.path, roots)
        # Auxiliary code (docs, tooling) counts only in a unit of that role; vendored code is in no unit of its own.
        counts = source.role not in AUXILIARY or source.role == role(unit, directory=True)
        if source.language is not None and counts:
            languages.setdefault(unit, set()).add(source.language)
    # What a build file builds counts for its unit too, unless the build file only declares a workspace.
    for build in facts.of(BuildFile):
        if (directory := _directory(build)) not in workspaces or languages.get(directory):
            languages.setdefault(owner(directory, roots), set()).update(build.languages)
    for content in facts.of(ContentLanguages):
        languages.setdefault(".", set()).update(content.languages)
    for directory in sorted(languages, key=lambda root: (root != ".", root)):
        if (purpose := role(directory, directory=True)) == "vendored":
            continue
        yield Unit(
            role=purpose,
            origin=Origin(path=directory),
            build_systems=tuple(roots.get(directory, ())),
            languages=frozenset(languages[directory]),
        )


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
    yield from _units(project, Facts((*plain, *ambiguous)))


__all__ = [
    "NOT_SOURCE_SUFFIXES",
    "BuildFile",
    "ContentLanguages",
    "SourceFile",
    "Unit",
    "UnrecognisedSuffix",
    "project_languages",
    "structure_facts",
]
