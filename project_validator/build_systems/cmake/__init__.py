"""CMake, read without running it: the CMake files are parsed and evaluated as configuring would evaluate them (see
`evaluation`), and the presets are read. What they set becomes facts (see `project_validator.facts.build`): compiler
and linker options and build settings, each for the builds it applies to, CTest tests, and the dependencies CPM and
FetchContent declare. `cmake --build` runs the commands of the custom targets it builds.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.build_systems.cmake.build import CMAKE as CMAKE_BUILD_SYSTEM
from project_validator.build_systems.cmake.build import CMAKE_PACKAGE_MANAGERS
from project_validator.build_systems.cmake.commands import Collector, CustomTarget
from project_validator.build_systems.cmake.ctest import BUILT_TESTS, CTEST
from project_validator.build_systems.cmake.evaluation import Evaluation
from project_validator.build_systems.cmake.presets import PRESET_FILES, preset_facts
from project_validator.core import Context, Project
from project_validator.facts import Command, Fact, Origin, Unknown, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.expansion import CommandExpander, Expansion, Script
from project_validator.facts.roles import role
from project_validator.facts.settings import SettingsReader

CMAKE_FILES = ("CMakeLists.txt", "*.cmake")


@dataclass(frozen=True, slots=True, kw_only=True)
class CMakeProject:
    """What a project's CMake files set (as facts), and the custom targets they define, by name."""

    facts: tuple[Fact, ...]
    targets: Mapping[str, tuple[CustomTarget, ...]]


def _evaluated(files: Mapping[str, str]) -> CMakeProject:
    collector = Collector()
    evaluation = Evaluation(files=frozenset(files), read=files.__getitem__, observer=collector)
    evaluation.evaluate()
    problems = (
        Unknown(
            origin=Origin(path=path),
            subject=f"the CMake file {path}",
            reason=reason,
            hides="settings",
            tools=("CMake",),
        )
        for path, reason in evaluation.problems.items()
    )
    targets = {
        name: tuple(
            CustomTarget(
                name=target.name,
                all=target.all,
                commands=target.commands,
                depends=(*target.depends, *collector.dependencies.get(name, ())),
                directory=target.directory,
            )
            for target in found
        )
        for name, found in collector.targets.items()
    }
    return CMakeProject(facts=tuple(dict.fromkeys((*collector.facts, *problems))), targets=targets)


def _files(project: Project, patterns: Iterable[str]) -> dict[str, str]:
    """The project's own files (not vendored code's) that `patterns` name, with their text."""
    names = tuple(patterns)
    paths = (path for path in project.files() if role(path) != "vendored")
    return {path: project.read_text(path) for path in paths if any(PurePosixPath(path).match(name) for name in names)}


def cmake_project(context: Context) -> CMakeProject:
    """The evaluation of the project's CMake files, made once."""
    return context.shared("CMake", lambda: _evaluated(_files(context.project, CMAKE_FILES)))


def _read_cmake(context: Context) -> Iterator[Fact]:
    yield from cmake_project(context).facts
    yield from preset_facts(_files(context.project, PRESET_FILES))


CMAKE = SettingsReader(name="CMake", files=(*CMAKE_FILES, *PRESET_FILES), read_project=_read_cmake)

# --- custom targets

_BUILT_BY_ALL = ("all", "ALL_BUILD")


def _built(argv: tuple[str, ...]) -> list[str]:
    """The targets `cmake --build` builds: those after `--target` (or `-t`), else every `ALL` target."""
    targets: list[str] = []
    naming = False
    for word in argv[2:]:
        if word in ("--target", "-t"):
            naming = True
        elif word.startswith("-"):
            naming = False
        elif naming:
            targets.append(word)
    return targets or ["all"]


def _scripts(project: CMakeProject, name: str, built: set[tuple[str, str]]) -> Iterator[Script]:
    """The commands building the custom target `name` runs, after those of the custom targets it depends on."""
    found = (
        [target for targets in project.targets.values() for target in targets if target.all]
        if name in _BUILT_BY_ALL
        else project.targets.get(name, ())
    )
    for target in found:
        if (target.name, target.directory) in built:
            continue
        built.add((target.name, target.directory))
        for dependency in target.depends:
            yield from _scripts(project, dependency, built)
        for argv, origin in target.commands:
            yield Script(
                text=shlex.join(argv), origin=origin, directory=None if target.directory == "." else target.directory
            )


def _custom_targets(command: Command, context: Context) -> list[Expansion] | None:
    """`cmake --build <dir> [--target <name>...]`: the commands of the custom targets it builds."""
    argv = resolved(command)
    if not starts_with(argv, ("cmake", "--build")):
        return None
    project = cmake_project(context)
    built: set[tuple[str, str]] = set()
    scripts: list[Expansion] = [script for name in _built(argv) for script in _scripts(project, name, built)]
    return scripts or None


CUSTOM_TARGETS = CommandExpander(name="CMake custom targets", expand=_custom_targets)

__all__ = [
    "BUILT_TESTS",
    "CMAKE",
    "CMAKE_BUILD_SYSTEM",
    "CMAKE_FILES",
    "CMAKE_PACKAGE_MANAGERS",
    "CTEST",
    "CUSTOM_TARGETS",
    "PRESET_FILES",
    "CMakeProject",
    "cmake_project",
]
