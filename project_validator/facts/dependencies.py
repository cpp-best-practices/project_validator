"""Dependencies: where the project declares the packages it depends on, which package manager resolves them, and where
their versions are locked.

A package manager's manifests and lockfiles are read by ordinary settings readers (see
`project_validator.facts.settings`), which record what they find as the facts here: a manifest that `Declared`
dependencies, a lockfile (or a setting) that `Locked` them, and whether a package is an `Application` or a `Library`,
which decides whether its lock is asked for. A `PackageManager` says how its facts are judged.
"""

import enum
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.components import known
from project_validator.facts import Command, Fact, Origin
from project_validator.facts.settings import Read, SettingsReader, unreadable


@dataclass(frozen=True, slots=True, kw_only=True)
class Declared(Fact):
    """A manifest (`Cargo.toml`, a `CMakeLists.txt` that calls CPM) that declares dependencies `manager` resolves."""

    manager: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Locked(Fact):
    """A lockfile (`Cargo.lock`), or a setting (Maven's `--strict-checksums`), that pins or verifies the
    dependencies `manager` resolves, for the directory it is in and those below it."""

    manager: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Application(Fact):
    """A package that is an application (a binary crate, an Xcode app), which locks its dependencies."""

    manager: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Library(Fact):
    """A package that is a library (a gem, a Composer library), whose users resolve its dependencies themselves."""

    manager: str


class Lock(enum.StrEnum):
    """When a package manager's lock is asked for: `always` (a package's lockfile is not published, so even a
    library commits one), for `applications` only, or `never` (the manager has no lockfile)."""

    ALWAYS = "always"
    APPLICATIONS = "applications"
    NEVER = "never"


def _never(_command: Command) -> bool:
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageManager:
    """A package manager of `languages`. `lock` says when its lock is asked for; for `applications`, a package with
    neither an `Application` nor a `Library` fact is an application when `applications_by_default`. `lock_hint` says how
    to lock. A `suggested` manager is suggested to a project that declares no dependencies (C and C++ have no package
    manager of their own). `verified_by` recognises a CI command that verifies the dependencies (`mvn
    --strict-checksums`), and `vendor_outputs` the files that show a vendored directory is the manager's own output
    (`vendor/modules.txt`)."""

    name: str
    languages: frozenset[str]
    lock: Lock = Lock.ALWAYS
    applications_by_default: bool = True
    lock_hint: str = ""
    suggested: bool = False
    verified_by: Callable[[Command], bool] = _never
    # Whether a lockfile deeper in a unit locks it (`requirements/dev.txt`), or only those beside or below it (a
    # `cabal.project.freeze` locks the project beside it).
    nested_locks: bool = True
    vendor_outputs: tuple[str, ...] = ()


def known_package_managers() -> tuple[PackageManager, ...]:
    """Every package manager defined by a module of the shared build systems, the shared tools or a profile."""
    return known(PackageManager)


type Recognise = Callable[[str, str], bool]


def _no(_path: str, _text: str) -> bool:
    return False


def _manifest(manager: str, declares: Recognise, application: Recognise, library: Recognise) -> Read:
    def read(path: str, text: str) -> Iterator[Fact]:
        origin = Origin(path=path)
        try:
            found = [
                kind(origin=origin, manager=manager)
                for kind, recognises in ((Declared, declares), (Application, application), (Library, library))
                if recognises(path, text)
            ]
        except ValueError as error:  # a manifest that does not parse (TOML and JSON errors are ValueErrors)
            yield unreadable(manager, path, error)
            return
        yield from found

    return read


def manifest_reader(
    *,
    name: str,
    manager: str,
    files: tuple[str, ...],
    declares: Recognise,
    application: Recognise = _no,
    library: Recognise = _no,
) -> SettingsReader:
    """A reader of `manager`'s manifests `files`: whether each `declares` dependencies, and is an `application` or a
    `library`; a manifest that does not parse is unknown."""
    return SettingsReader(name=name, files=files, read=_manifest(manager, declares, application, library))


def lockfile_reader(*, manager: str, files: tuple[str, ...], name: str = "") -> SettingsReader:
    """A reader of `manager`'s lockfiles `files`, which lock dependencies by being there (and committed)."""
    return SettingsReader(
        name=name or f"{manager} lockfile",
        files=files,
        read=lambda path, _text: iter((Locked(origin=Origin(path=path), manager=manager),)),
    )


def directory_of(path: str) -> str:
    return str(PurePosixPath(path).parent)


def managers_of(language: str, managers: Iterable[PackageManager]) -> tuple[PackageManager, ...]:
    return tuple(manager for manager in managers if language in manager.languages)


__all__ = [
    "Application",
    "Declared",
    "Library",
    "Lock",
    "Locked",
    "PackageManager",
    "directory_of",
    "known_package_managers",
    "lockfile_reader",
    "managers_of",
    "manifest_reader",
]
