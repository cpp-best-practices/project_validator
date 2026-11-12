"""Structure facts: the project's source files and their languages (or formats), its build files, and what its
content shows.

The project map (`--map`, `project_validator.project_map`) is a view over these facts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems import Ecosystem, Kind, build_systems, formats, registered
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.auxiliary import AuxiliaryCode, Selectors
from project_validator.facts.roles import role
from project_validator.facts.tools import owner, within

# Suffixes of files that are not source code of any language: documents, styles, media, archives, binaries and plain
# data or configuration no format ecosystem claims. They, and editor backups (`main.cpp~`), are never reported as
# unrecognised.
NOT_SOURCE_SUFFIXES = frozenset(
    {
        *(".md", ".markdown", ".rst", ".txt", ".adoc", ".dox", ".pdf", ".html", ".htm"),
        *(".css", ".scss", ".sass", ".less", ".map"),
        *(".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".mp3", ".mp4", ".wav"),
        *(".ttf", ".otf", ".woff", ".woff2"),
        *(".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar", ".whl", ".jar"),
        *(".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj", ".lib", ".pdb", ".class", ".pyc"),
        *(".ini", ".cfg", ".conf", ".csv", ".tsv", ".lock", ".env"),
        *(".log", ".diff", ".patch", ".orig", ".bak", ".swp"),
        # Templates (config.h.in, MANIFEST.in) can belong to any language.
        ".in",
    }
)
# Hidden top-level directories that hold configuration. A format's files are read there too (CI workflows and
# editor settings are data); a language's are not (a helper script in `.github/scripts` makes no language the
# project's).
CONFIGURATION_DIRECTORIES = frozenset({".github", ".gitlab", ".circleci", ".buildkite", ".devcontainer", ".vscode"})


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFile(Fact):
    """A source file, its language or format (None for a file of an ecosystem that adds no language, such as a `.h`
    file of a C++ project) and its `role` (see `role`). `ambiguous` files count once their ecosystem is recognised
    another way; vendored files (other projects' code, minified bundles) are recorded but make no language the
    project's."""

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
    the languages, and the formats, of the sources in it (outside the units below it).

    A unit is the outermost directory with a build system's files (a CMake project's subdirectories, a Maven
    project's modules belong to it), or a member of a workspace a build file declares (npm workspaces, Cargo and uv
    workspaces, go.work). Sources outside every unit, and languages only content shows, belong to the root unit. A
    unit's languages are those of its own code, whatever its role: vendored code adds none, and the code
    `--auxiliary` names adds none (it is judged apart, as advisory). A project with one unit is judged as before; a
    monorepo or a mixed-language project is judged unit by unit.
    """

    build_systems: tuple[str, ...]
    languages: frozenset[str]
    formats: frozenset[str] = frozenset()
    # What the unit is for, by its directory (see `role`); a name, not a judgement.
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
    from project_validator.project_map import build_files

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


def _source_suffixes() -> dict[str, tuple[str, Kind]]:
    """Suffix -> the language or format its files are sources of, and which of the two it is."""
    return {
        suffix: (name, ecosystem.kind)
        for ecosystem in registered()
        for suffix, name in (ecosystem.source_suffixes or {}).items()
    }


def _source_names() -> tuple[tuple[str, str, Kind], ...]:
    """(file name pattern, the language or format, which of the two) of the sources with no telling suffix."""
    return tuple(
        (pattern, name, ecosystem.kind)
        for ecosystem in registered()
        for pattern, name in (ecosystem.source_names or {}).items()
    )


def _by_name(path: str) -> tuple[str, str, Kind] | None:
    """The name pattern that recognises the file at `path` as a source, with its language or format."""
    name = PurePosixPath(path).name
    return next((found for found in _source_names() if fnmatchcase(name, found[0])), None)


def source_signal(path: str) -> str:
    """What recognises the source at `path`: its suffix, or, for a source with no telling suffix, the name pattern
    (`Dockerfile.*`)."""
    suffix = PurePosixPath(path).suffix
    if suffix in _source_suffixes() or (found := _by_name(path)) is None:
        return suffix
    return found[0]


def _ambiguous(files: list[str], confirmed: list[Ecosystem]) -> Iterator[SourceFile]:
    for ecosystem in confirmed:
        for suffix, language in sorted((ecosystem.ambiguous_suffixes or {}).items()):
            for path in files:
                if PurePosixPath(path).suffix == suffix:
                    origin = Origin(path=path)
                    yield SourceFile(origin=origin, language=language, ambiguous=True, role=role(path))


def _own_sources(facts: Facts) -> Iterator[str]:
    """The language or format of each of the project's own sources. Vendored code (other projects' code, minified
    bundles) adds none."""
    return (source.language for source in facts.of(SourceFile) if source.language is not None and not source.vendored)


def project_languages(facts: Facts) -> frozenset[str]:
    """The languages the project uses: those its build files build, its own sources are written in, or its content
    shows; not its formats."""
    known = formats()
    return frozenset(
        {
            *(language for build in facts.of(BuildFile) for language in build.languages),
            *(name for name in _own_sources(facts) if name not in known),
            *(language for content in facts.of(ContentLanguages) for language in content.languages),
        }
    )


def project_formats(facts: Facts) -> frozenset[str]:
    """The formats the project's own files are in."""
    known = formats()
    return frozenset(name for name in _own_sources(facts) if name in known)


def _configuration(path: str) -> bool:
    return PurePosixPath(path).parts[0] in CONFIGURATION_DIRECTORIES


def _sources(project: Project) -> Iterator[SourceFile]:
    """The sources of each language among the project's files, and of each format among those and the configuration
    directories' files."""
    known = _source_suffixes()
    for path in project.files(hidden=CONFIGURATION_DIRECTORIES):
        found = known.get(PurePosixPath(path).suffix)
        if found is None and (named := _by_name(path)) is not None:
            found = named[1:]
        if found is not None and (found[1] == "format" or not _configuration(path)):
            yield SourceFile(origin=Origin(path=path), language=found[0], role=role(path))


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


def _own(languages: Iterable[str], path: str, named: Selectors, *, directory: bool = False) -> set[str]:
    """The languages of `languages` that the code at `path` (a file, or a `directory`) has as the product's: those
    `--auxiliary` does not name it in."""
    return {language for language in languages if not named.matching(path, language, directory=directory)}


type _ByUnit = dict[str, set[str]]


def _sources_by_unit(facts: Facts, roots: Iterable[str], named: Selectors) -> tuple[_ByUnit, _ByUnit]:
    """Unit -> the languages, and unit -> the formats, of the sources in it (outside the units below it). Vendored
    code is in no unit of its own; the code `--auxiliary` names adds no language (or format) to its unit."""
    known, roots = formats(), tuple(roots)
    languages: _ByUnit = {".": set(), **{root: set() for root in roots}}
    formats_: _ByUnit = {}
    for source in facts.of(SourceFile):
        if source.language is not None and not source.vendored:
            found = formats_ if source.language in known else languages
            found.setdefault(owner(source.path, roots), set()).update(_own([source.language], source.path, named))
    return languages, formats_


def _units(project: Project, facts: Facts, named: Selectors) -> Iterator[Unit]:
    roots, workspaces = _unit_roots(project, facts.of(BuildFile))
    languages, formats_ = _sources_by_unit(facts, roots, named)
    # What a build file builds counts for its unit too, unless the build file only declares a workspace.
    for build in facts.of(BuildFile):
        if (directory := _directory(build)) not in workspaces or languages.get(directory):
            languages.setdefault(owner(directory, roots), set()).update(_own(build.languages, build.origin.path, named))
    for content in facts.of(ContentLanguages):
        languages["."].update(_own(content.languages, ".", named, directory=True))
    for directory in sorted(languages, key=lambda root: (root != ".", root)):
        if (purpose := role(directory, directory=True)) == "vendored":
            continue
        yield Unit(
            role=purpose,
            origin=Origin(path=directory),
            build_systems=tuple(roots.get(directory, ())),
            languages=frozenset(languages[directory]),
            formats=frozenset(formats_.get(directory, ())),
        )


def structure_facts(project: Project) -> Iterator[Fact]:
    """The build files, the source files with their languages, what the content shows, the ambiguous sources of the
    ecosystems those show, and the unrecognised suffixes."""
    files = project.files()
    named = Selectors.parse(project.auxiliary)
    yield AuxiliaryCode(origin=Origin(path="."), named=tuple(project.auxiliary))
    found = list(_build_files(project, files))
    plain = Facts((*(fact for fact, _ in found if fact is not None), *_sources(project), *_content(project)))
    yield from plain
    names = project_languages(plain) | project_formats(plain)
    ambiguous = list(_ambiguous(files, [ecosystem for ecosystem in registered() if ecosystem.languages & names]))
    yield from ambiguous
    sources = (*plain.of(SourceFile), *ambiguous)
    recognised = {signal for source in sources if (signal := source_signal(source.path)).startswith(".")}
    yield from _unrecognised(files, {*(path for _, path in found), *(source.path for source in sources)}, recognised)
    yield from _units(project, Facts((*plain, *ambiguous)), named)


__all__ = [
    "CONFIGURATION_DIRECTORIES",
    "NOT_SOURCE_SUFFIXES",
    "BuildFile",
    "ContentLanguages",
    "SourceFile",
    "Unit",
    "UnrecognisedSuffix",
    "project_formats",
    "project_languages",
    "source_signal",
    "structure_facts",
]
