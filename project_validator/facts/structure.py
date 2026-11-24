"""Structure facts: the project's source files and their languages (or formats), its build files, and what its
content shows.

The project map (`--map`, `project_validator.project_map`) is a view over these facts.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems import Ecosystem, Kind, build_systems, families, formats, registered
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.auxiliary import AuxiliaryCode, Selectors
from project_validator.facts.roles import AUXILIARY, fixture_data, role
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
        # Lock files, test plans and data the profiles' tools write or read (cabal.project.freeze, Package.resolved,
        # Xcode test plans, R's data and Windows Makevars), templates (EEx, Terraform's templatefile, `.tpl`),
        # cheatsheets and AsciiDoc.
        *(".freeze", ".resolved", ".xctestplan", ".rda", ".rds", ".rdata", ".win"),
        *(".eex", ".heex", ".leex", ".tftpl", ".tpl", ".cheatmd", ".asciidoc"),
    }
)
# Java's service-provider files are named after the interface they implement (`com.example.Spi`).
_SERVICE_PROVIDERS = "META-INF/services/"
# The suffixes of the languages build files name that no profile reads (CMake's `LANGUAGES CUDA OBJC`).
BUILT_LANGUAGE_SUFFIXES = {
    "CUDA": (".cu", ".cuh"),
    "Objective-C": (".m",),
    "Objective-C++": (".mm",),
}
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
    """Languages (or formats) an ecosystem's probe found in the project's content, for intent that file names cannot
    show."""

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
    # For a unit of tests, the units it tests: those it depends on by path and the unit it is in (upstream #230);
    # none: every unit (see `tests_unit`).
    tests: tuple[str, ...] = ()

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


def source_languages() -> Callable[[str], str | None]:
    """A lookup of the language or format the file at a path is a source of (by suffix, else by name), or None."""
    suffixes = _source_suffixes()

    def language(path: str) -> str | None:
        if (found := suffixes.get(PurePosixPath(path).suffix)) is not None:
            return found[0]
        named = _by_name(path)
        return named[1] if named is not None else None

    return language


def source_signal(path: str) -> str:
    """What recognises the source at `path`: its suffix, or, for a source with no telling suffix, the name pattern
    (`Dockerfile.*`)."""
    suffix = PurePosixPath(path).suffix
    if suffix in _source_suffixes() or (found := _by_name(path)) is None:
        return suffix
    return found[0]


def _ambiguous(
    files: list[str], confirmed: list[Ecosystem], sources: Iterable[SourceFile], declared: frozenset[str]
) -> Iterator[SourceFile]:
    """The sources with a suffix the `confirmed` ecosystems claim ambiguously. A file several of them claim for
    different languages (a `.h` header, C's or C++'s) is the language of the sources around it (see `_neighbours`)."""
    claims: dict[str, list[str | None]] = {}
    for ecosystem in confirmed:
        for suffix, language in sorted((ecosystem.ambiguous_suffixes or {}).items()):
            for path in files:
                if PurePosixPath(path).suffix == suffix:
                    claims.setdefault(path, []).append(language)
    neighbours = _Neighbours(sources)
    for path, candidates in claims.items():
        named = list(dict.fromkeys(language for language in candidates if language is not None))
        language = named[0] if len(named) == 1 else neighbours.language(path, named, declared) if named else None
        yield SourceFile(origin=Origin(path=path), language=language, ambiguous=True, role=role(path))


class _Neighbours:
    """How many of the project's own sources of each language are below each directory."""

    def __init__(self, sources: Iterable[SourceFile]) -> None:
        self._below: dict[str, Counter[str]] = {}
        for source in sources:
            if source.language is not None and not source.vendored:
                for directory in _ancestors(source.path):
                    self._below.setdefault(directory, Counter())[source.language] += 1

    def language(self, path: str, candidates: list[str], declared: frozenset[str]) -> str:
        """Of `candidates`, the language of most sources below the nearest ancestor of `path` that has any of them
        (the first candidate on a tie); with none anywhere, the one candidate the build files `declared`, else the
        first."""
        for directory in _ancestors(path):
            counts = self._below.get(directory, Counter())
            if found := [language for language in candidates if counts[language]]:
                return max(found, key=lambda language: counts[language])
        only = [language for language in candidates if language in declared]
        return only[0] if len(only) == 1 else candidates[0]


def _ancestors(path: str) -> Iterator[str]:
    """The directories `path` is in, nearest first, ending with the project's root (".")."""
    parent = PurePosixPath(path).parent
    while str(parent) != ".":
        yield str(parent)
        parent = parent.parent
    yield "."


def _own_sources(facts: Facts) -> Iterator[str]:
    """The language or format of each of the project's own sources. Vendored code (other projects' code, minified
    bundles) adds none."""
    return (source.language for source in facts.of(SourceFile) if source.language is not None and not source.vendored)


def project_languages(facts: Facts) -> frozenset[str]:
    """The languages the project uses: those its build files build, its own sources are written in, or its content
    shows; not its formats."""
    known = formats()
    own = {name for name in _own_sources(facts) if name not in known}
    built = {language for build in facts.of(BuildFile) for language in build.languages}
    return frozenset({*given_way(built, own), *own, *(name for name in _content_names(facts) if name not in known)})


def given_way(declared: Iterable[str], sources: Iterable[str]) -> set[str]:
    """The languages build files `declared`, but the languages of a family give way to the `sources` when there are
    sources of the family (see `Ecosystem.family`): CMake's project() enables C and C++ unless told otherwise, and a
    package.json's `main` names the JavaScript a TypeScript package publishes, neither of which says which language
    the code is written in."""
    declared, sources = set(declared), set(sources)
    for family in families():
        if sources & family:
            declared -= family - sources
    return declared


def _tool_configuration(sources: list[SourceFile]) -> Iterator[SourceFile]:
    """`sources`, with the tool configuration of a family's language (`eslint.config.js`) adding no language where
    the family's other languages have sources of their own (a TypeScript project's)."""
    patterns = {
        language: (ecosystem.tool_configuration, family)
        for ecosystem in registered()
        if ecosystem.tool_configuration and ecosystem.family
        for family in families()
        if ecosystem.languages <= family
        for language in ecosystem.languages
    }

    def configuration(source: SourceFile) -> bool:
        found = patterns.get(source.language or "")
        return found is not None and any(fnmatchcase(PurePosixPath(source.path).name, glob) for glob in found[0])

    own = {source.language for source in sources if not source.vendored and not configuration(source)}
    for source in sources:
        family = patterns[source.language or ""][1] if configuration(source) else frozenset()
        given = configuration(source) and bool(own & (family - {source.language}))
        yield replace(source, language=None) if given else source


def _content_names(facts: Facts) -> Iterator[str]:
    """The languages and formats the content probes found."""
    return (name for content in facts.of(ContentLanguages) for name in content.languages)


def project_formats(facts: Facts) -> frozenset[str]:
    """The formats the project's own files are in, or that its content shows (a Kubernetes manifest is YAML)."""
    known = formats()
    return frozenset(name for name in (*_own_sources(facts), *_content_names(facts)) if name in known)


def _configuration(path: str) -> bool:
    return PurePosixPath(path).parts[0] in CONFIGURATION_DIRECTORIES


# Editor settings written in a language's syntax (Emacs' per-directory variables): settings, not sources.
_EDITOR_SETTINGS = frozenset({".dir-locals.el", ".dir-locals-2.el"})


def _generated(project: Project) -> frozenset[str]:
    """The directories an ecosystem's own build generates and builds (see `Ecosystem.generated_directories`)."""
    return frozenset(
        directory
        for ecosystem in registered()
        if ecosystem.generated_directories is not None
        for directory in ecosystem.generated_directories(project)
    )


def _environments(project: Project, sources: list[SourceFile]) -> frozenset[str]:
    """The files that only set up a developer's environment (see `Ecosystem.environment_files`), when the sources
    of other languages are the project's; none when the environment's language is all there is."""
    found = {
        (path, language)
        for ecosystem in registered()
        if ecosystem.environment_files is not None
        for path in ecosystem.environment_files(project)
        for language in ecosystem.languages
    }
    paths = {path for path, _ in found}
    languages = {language for _, language in found}
    others = {
        source.language
        for source in sources
        if source.language and not source.vendored and source.path not in paths and source.language not in languages
    }
    return frozenset(paths) if others else frozenset()


def _test_units(project: Project) -> frozenset[str]:
    """The units an ecosystem's build files say are units of tests (see `Ecosystem.test_units`)."""
    return frozenset(
        directory
        for ecosystem in registered()
        if ecosystem.test_units is not None
        for directory in ecosystem.test_units(project)
    )


def _outside(paths: Iterable[str], directories: frozenset[str]) -> list[str]:
    return [path for path in paths if not any(within(path, directory) for directory in directories)]


def _sources(project: Project, generated: frozenset[str]) -> Iterator[SourceFile]:
    """The sources of each language among the project's files, and of each format among those and the configuration
    directories' files; not editor settings, nor what an ecosystem's build generates (`generated`)."""
    known = _source_suffixes()
    for path in _outside(project.files(hidden=CONFIGURATION_DIRECTORIES), generated):
        if PurePosixPath(path).name in _EDITOR_SETTINGS:
            continue
        found = known.get(PurePosixPath(path).suffix)
        if found is None and (named := _by_name(path)) is not None:
            found = named[1:]
        if found is not None and (found[1] == "format" or not _configuration(path)):
            yield SourceFile(origin=Origin(path=path), language=found[0], role=role(path))


def _located(ecosystem: Ecosystem, found: Iterable[tuple[str, str]]) -> Iterator[ContentLanguages]:
    """What a probe found, by the directory that holds it."""
    directories: dict[str, set[str]] = {}
    for path, language in found:
        directories.setdefault(str(PurePosixPath(path).parent), set()).add(language)
    for directory, names in sorted(directories.items()):
        yield ContentLanguages(origin=Origin(path=directory), ecosystem=ecosystem.label, languages=frozenset(names))


def _content(project: Project) -> tuple[list[ContentLanguages], set[str]]:
    """What each ecosystem's probe finds, where it says (each directory holding what it found) or for the project,
    and the files it says it found (which no suffix needs to account for)."""
    content: list[ContentLanguages] = []
    paths: set[str] = set()
    for ecosystem in registered():
        if ecosystem.locate is not None:
            found = [(path, name) for path, name in ecosystem.locate(project) if name in ecosystem.languages]
            paths.update(path for path, _ in found)
            content.extend(_located(ecosystem, found))
        elif ecosystem.detect is not None and (languages := ecosystem.detect(project) & ecosystem.languages):
            content.append(ContentLanguages(origin=Origin(path="."), ecosystem=ecosystem.label, languages=languages))
    return content, paths


def _version(path: PurePosixPath, suffix: str) -> bool:
    """Whether `suffix` is the end of a version the file is named for (pyenv's `3.12.0`, `3.13.0t`, `3.4-dev`), not a
    file type: all digits, or a digit after a name that ends in one (`.4th` after `words` is a file type)."""
    return suffix[1:].isdigit() or (suffix[1:2].isdigit() and path.stem[-1:].isdigit())


def _unrecognised(files: list[str], accounted: set[str], recognised: set[str]) -> Iterator[UnrecognisedSuffix]:
    """The suffixes of the source-like files no ecosystem accounts for, most common first."""
    counts = Counter(
        suffix
        for path in files
        if path not in accounted
        and (suffix := PurePosixPath(path).suffix)
        and suffix not in recognised
        and not _version(PurePosixPath(path), suffix)
        and suffix.lower() not in NOT_SOURCE_SUFFIXES
        and not suffix.endswith("~")
        and _SERVICE_PROVIDERS not in path
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


def _standalone(project: Project, builds: list[BuildFile]) -> set[str]:
    """The directories of `builds` (of one build system) whose build file is a project of its own wherever it is (a
    nested Package.swift: see `BuildSystem.standalone`), but for test suites' data (`tests/fixtures/`)."""
    system = next((found for found in build_systems() if found.name == builds[0].build_system), None)
    if system is None or system.standalone is None:
        return set()
    files = (build for build in builds if not build.origin.path.endswith("/") and not fixture_data(build.origin.path))
    return {_directory(build) for build in files if system.standalone(project.read_text(build.origin.path))}


def _unit_roots(project: Project, builds: tuple[BuildFile, ...]) -> tuple[dict[str, list[str]], set[str]]:
    """Unit directory -> its build systems (each build system's outermost directories, workspace members, and the
    projects of their own below them: upstream #188), and the directories of the build files that declare a
    workspace."""
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
        standalone = _standalone(project, own)
        for directory in sorted(directories):
            declared_member = any(fnmatchcase(directory, pattern) for pattern in members)
            outer = not any(other != directory and within(directory, other) for other in directories)
            if declared_member or outer or directory in standalone:
                roots.setdefault(directory, []).append(system)
    return roots, workspaces


def _languages_by_purpose(facts: Facts) -> tuple[set[str], set[str]]:
    """The languages and formats of the project's own sources in product code, and those in auxiliary code."""
    product: set[str] = set()
    auxiliary: set[str] = set()
    for source in facts.of(SourceFile):
        if source.language is not None and not source.vendored:
            (auxiliary if source.role in AUXILIARY else product).add(source.language)
    return product, auxiliary


def _auxiliary_languages(facts: Facts) -> frozenset[str]:
    """The languages (and formats) written only in auxiliary code (upstream #182): a test fixture in C, a docs
    theme's script, a maintainer's script under `hack/`, a formatter's test notebooks, that no build file outside
    auxiliary code builds, and of an ecosystem none of whose languages is the product's (a Java project's tests in
    Kotlin are its own); none when the project has no product language left (a project of examples alone is judged
    as it is). The product left is its languages and the content the probes find (a Helm chart): a format's files
    alone (CI's YAML, a `renovate.json`) leave no product."""
    product, auxiliary = _languages_by_purpose(facts)
    built = (build for build in facts.of(BuildFile) if role(_directory(build), directory=True) not in AUXILIARY)
    product |= given_way((language for build in built for language in build.languages), product)
    product |= set(_content_names(facts))
    product |= {
        language for ecosystem in registered() if ecosystem.languages & product for language in ecosystem.languages
    }
    return frozenset(auxiliary - product) if product - _plain_formats(facts) else frozenset()


def _plain_formats(facts: Facts) -> set[str]:
    """The formats that are no product on their own: every format but the content a probe found (a Helm chart)."""
    return set(formats()) - set(_content_names(facts))


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
            unit = languages.setdefault(owner(directory, roots), set())
            unit.update(given_way(_own(build.languages, build.origin.path, named), unit))
    known = formats()
    for content in facts.of(ContentLanguages):
        names = _own(content.languages, content.origin.path, named, directory=True)
        holder = owner(content.origin.path, roots)
        languages.setdefault(holder, set()).update(names - known)
        formats_.setdefault(holder, set()).update(names & known)
    tests = _test_units(project)
    for directory in sorted(languages, key=lambda root: (root != ".", root)):
        if (purpose := role(directory, directory=True)) == "vendored":
            continue
        purpose = "test" if directory in tests else purpose
        yield Unit(
            role=purpose,
            origin=Origin(path=directory),
            build_systems=tuple(roots.get(directory, ())),
            languages=frozenset(languages[directory]),
            formats=frozenset(formats_.get(directory, ())),
            tests=_tested(project, facts, directory, tuple(languages)) if purpose == "test" else (),
        )


def _tested(project: Project, facts: Facts, directory: str, units: tuple[str, ...]) -> tuple[str, ...]:
    """The units a unit of tests at `directory` tests: those its build files depend on by path, and the unit it is in
    but for the root (hledger-web/test/browser tests hledger-web); none when neither is known (it tests every unit)."""
    others = tuple(unit for unit in units if unit != directory)
    found = [owner(path, others) for path in _path_dependencies(project, facts, directory)]
    if directory != "." and (parent := owner(str(PurePosixPath(directory).parent), others)) != ".":
        found.append(parent)
    return tuple(dict.fromkeys(unit for unit in found if unit != directory))


def _path_dependencies(project: Project, facts: Facts, directory: str) -> Iterator[str]:
    """The project paths of the packages the build files at `directory` depend on by path."""
    systems = {system.name: system for system in build_systems()}
    for build in facts.of(BuildFile):
        system = systems.get(build.build_system)
        if _directory(build) != directory or system is None or system.path_dependencies is None:
            continue
        for path in system.path_dependencies(project.read_text(build.origin.path)):
            yield posixpath.normpath(posixpath.join(directory, path))


def tests_unit(facts: Facts) -> Callable[[str, str], bool]:
    """Whether a path is in a unit of tests (a separate test project) that tests a unit (see `Unit.tests`)."""
    units = {found.directory: found for found in facts.of(Unit)}

    def tests(path: str, unit: str) -> bool:
        found = units.get(owner(path, units))
        return found is not None and found.role == "test" and (not found.tests or unit in found.tests)

    return tests


type _Found = list[tuple[BuildFile | None, str]]


def _builds_and_sources(
    project: Project, files: list[str], generated: frozenset[str]
) -> tuple[_Found, list[SourceFile]]:
    """The build files and the sources among `files` (see `_build_files`, `_sources`); a developer environment's
    files (see `_environments`) are neither builds nor sources of a language."""
    sources = list(_tool_configuration(list(_sources(project, generated))))
    environments = _environments(project, sources)
    found = [(build, path) for build, path in _build_files(project, files) if path not in environments]
    return found, [replace(source, language=None) if source.path in environments else source for source in sources]


def structure_facts(project: Project) -> Iterator[Fact]:
    """The build files, the source files with their languages, what the content shows, the ambiguous sources of the
    ecosystems those show, and the unrecognised suffixes."""
    generated = _generated(project)
    files = _outside(project.files(), generated)
    found, found_sources = _builds_and_sources(project, files, generated)
    content, located = _content(project)
    plain = Facts((*(fact for fact, _ in found if fact is not None), *found_sources, *content))
    yield from plain
    names = project_languages(plain) | project_formats(plain)
    confirmed = [ecosystem for ecosystem in registered() if ecosystem.languages & names]
    declared = frozenset(language for build in plain.of(BuildFile) for language in build.languages)
    ambiguous = list(_ambiguous(files, confirmed, plain.of(SourceFile), declared))
    yield from ambiguous
    sources = (*plain.of(SourceFile), *ambiguous)
    recognised = {signal for source in sources if (signal := source_signal(source.path)).startswith(".")}
    recognised |= {suffix for name in names for suffix in BUILT_LANGUAGE_SUFFIXES.get(name, ())}
    accounted = {*(path for _, path in found), *(source.path for source in sources), *located}
    yield from _unrecognised(files, accounted, recognised)
    every = Facts((*plain, *ambiguous))
    implied = _auxiliary_languages(every)
    named = Selectors.parse(project.auxiliary, implied)
    yield AuxiliaryCode(origin=Origin(path="."), named=tuple(project.auxiliary), implied=tuple(sorted(implied)))
    yield from _units(project, every, named)


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
    "source_languages",
    "source_signal",
    "structure_facts",
    "tests_unit",
]
