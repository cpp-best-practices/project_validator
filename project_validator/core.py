"""Core types shared by the validator, its checks and its CI providers."""

import enum
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, CiProvider
    from project_validator.structure import ProjectStructure


class Status(enum.StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True, kw_only=True)
class Result:
    status: Status
    message: str
    details: tuple[str, ...] = ()

    @classmethod
    def passed(cls, message: str, *details: str) -> Result:
        return cls(status=Status.PASS, message=message, details=details)

    @classmethod
    def warned(cls, message: str, *details: str) -> Result:
        return cls(status=Status.WARN, message=message, details=details)

    @classmethod
    def failed(cls, message: str, *details: str) -> Result:
        return cls(status=Status.FAIL, message=message, details=details)

    def with_details(self, *details: str) -> Result:
        return Result(status=self.status, message=self.message, details=self.details + details)


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    build: bool = False
    cmake: str = "cmake"
    ctest: str = "ctest"


_SKIPPED_DIRECTORIES = frozenset({"node_modules", "__pycache__"})


def _is_cmake_build_tree(directory: Path) -> bool:
    return (directory / "CMakeCache.txt").is_file()


def _is_cargo_target(directory: Path) -> bool:
    """Cargo tags its output with CACHEDIR.TAG and, by default, puts it in `target/` beside `Cargo.toml`."""
    return (directory / "CACHEDIR.TAG").is_file() or (
        directory.name == "target" and (directory.parent / "Cargo.toml").is_file()
    )


def _is_build_tree(directory: Path) -> bool:
    return _is_cmake_build_tree(directory) or _is_cargo_target(directory)


def _is_cmake_file(name: str) -> bool:
    return name == "CMakeLists.txt" or name.endswith(".cmake")


@dataclass(frozen=True, slots=True)
class Project:
    """Read-only view of the source tree being validated; paths are POSIX and relative to `root`."""

    root: Path

    def exists(self, relative: str) -> bool:
        return (self.root / relative).is_file()

    def read_text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8", errors="replace")

    def files_in(self, relative_directory: str, suffixes: tuple[str, ...]) -> list[str]:
        directory = self.root / relative_directory
        if not directory.is_dir():
            return []
        return sorted(
            str(PurePosixPath(relative_directory, entry.name))
            for entry in directory.iterdir()
            if entry.is_file() and entry.name.endswith(suffixes)
        )

    def files(self) -> list[str]:
        """Every file of the project, skipping hidden directories, vendored packages and CMake/Cargo build trees."""
        return sorted(self._walk_files())

    def cmake_files(self) -> list[str]:
        return [path for path in self.files() if _is_cmake_file(PurePosixPath(path).name)]

    def _walk_files(self) -> Iterator[str]:
        for directory, subdirectories, files in os.walk(self.root):
            current = Path(directory)
            subdirectories[:] = [
                name
                for name in subdirectories
                if not name.startswith(".")
                and name not in _SKIPPED_DIRECTORIES
                and not _is_build_tree(current / name)
            ]
            relative = current.relative_to(self.root)
            yield from (str(PurePosixPath(relative, name)) for name in files)


class Context:
    """Everything a check may inspect; CI discovery is computed once and shared between checks."""

    def __init__(self, project: Project, providers: tuple[CiProvider, ...], options: Options) -> None:
        self.project = project
        self.providers = providers
        self.options = options

    @cached_property
    def ci_files(self) -> tuple[CiFile, ...]:
        from project_validator.ci import find_ci_files

        return find_ci_files(self.project, self.providers)

    @cached_property
    def ci_analysis(self) -> CiAnalysis:
        from project_validator.ci import parse_jobs

        return parse_jobs(self.project, self.ci_files)

    @cached_property
    def ci_texts(self) -> tuple[str, ...]:
        return tuple(self.project.read_text(ci_file.path) for ci_file in self.ci_files)

    @cached_property
    def structure(self) -> ProjectStructure:
        from project_validator.structure import map_project

        return map_project(self.project, self.ci_files, self.ci_analysis)

    @cached_property
    def cmake_texts(self) -> tuple[str, ...]:
        from project_validator.text import strip_cmake_comments

        return tuple(strip_cmake_comments(self.project.read_text(path)) for path in self.project.cmake_files())


type CheckFunction = Callable[[Context], Result]


@dataclass(frozen=True, slots=True, kw_only=True)
class Check:
    name: str
    description: str
    run: CheckFunction = field(repr=False)
    languages: frozenset[str] = frozenset()

    def applies_to(self, languages: frozenset[str]) -> bool:
        """A check without languages is language agnostic; a project whose languages are unknown gets every check."""
        return not self.languages or not languages or bool(self.languages & languages)


def check(
    *, name: str, description: str, languages: frozenset[str] = frozenset()
) -> Callable[[CheckFunction], Check]:
    """Turn a function taking a `Context` and returning a `Result` into a discoverable `Check`."""

    def wrap(function: CheckFunction) -> Check:
        return Check(name=name, description=description, run=function, languages=languages)

    return wrap
