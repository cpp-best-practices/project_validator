"""CMake, read without running it: the CMake files are parsed and evaluated as configuring would evaluate them (see
`evaluation`), and the presets are read. What they set becomes facts (see `project_validator.facts.build`): compiler
and linker options and build settings, each for the builds it applies to, CTest tests, and the dependencies CPM and
FetchContent declare. `cmake --build` runs the commands of the custom targets it builds.
"""

from __future__ import annotations

import posixpath
import re
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
from project_validator.facts.expansion import CommandExpander, Expansion, Script, joined
from project_validator.facts.roles import role
from project_validator.facts.settings import SettingsReader
from project_validator.facts.shell import command_line

CMAKE_FILES = ("CMakeLists.txt", "*.cmake")
# A configure_file() template (`configure_package_config_file`'s `@PACKAGE_INIT@`): a substitution where a command
# must be. It is rendered before CMake reads it, so it is not one of the project's CMake files.
_TEMPLATE = re.compile(r"^[ \t]*@[A-Za-z_]\w*@", re.MULTILINE)


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
    return context.shared("CMake", lambda: _evaluated(_untemplated(_files(context.project, CMAKE_FILES))))


def _untemplated(files: Mapping[str, str]) -> dict[str, str]:
    return {path: text for path, text in files.items() if not _TEMPLATE.search(text)}


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
                text=command_line(argv), origin=origin, directory=None if target.directory == "." else target.directory
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

# --- scripts


def _script_arguments(argv: tuple[str, ...]) -> tuple[dict[str, str], str | None]:
    """`cmake [-D name[:type]=value]... -P script`: the variables it defines, and the script (None: not `-P`)."""
    defines: dict[str, str] = {}
    words = iter(argv[1:])
    for word in words:
        if word == "-P":
            return defines, next(words, None)
        if word.startswith("-D"):
            definition = word[2:] or next(words, "")
            name, _, value = definition.partition("=")
            defines[name.partition(":")[0]] = value
    return defines, None


def _scripts_run(command: Command, context: Context) -> list[Expansion] | None:
    """`cmake -P script`: the commands the script's `execute_process()` calls run."""
    argv = resolved(command)
    if argv[:1] != ("cmake",):
        return None
    defines, script = _script_arguments(argv)
    path = posixpath.normpath(joined(command.directory, script)) if script else None
    if path is None or not context.project.exists(path):
        return None
    files = _untemplated(_files(context.project, CMAKE_FILES))
    collector = Collector()
    evaluation = Evaluation(files=frozenset(files), read=files.__getitem__, observer=collector)
    evaluation.script(path, defines)
    problems: list[Expansion] = [
        Unknown(origin=Origin(path=at), subject=f"the CMake script {at}", reason=reason, hides="commands")
        for at, reason in evaluation.problems.items()
    ]
    return [
        *problems,
        *(Script(text=command_line(argv), origin=origin) for argv, origin in collector.processes),
    ] or None


SCRIPTS = CommandExpander(name="CMake scripts", expand=_scripts_run)

__all__ = [
    "BUILT_TESTS",
    "CMAKE",
    "CMAKE_BUILD_SYSTEM",
    "CMAKE_FILES",
    "CMAKE_PACKAGE_MANAGERS",
    "CTEST",
    "CUSTOM_TARGETS",
    "PRESET_FILES",
    "SCRIPTS",
    "CMakeProject",
    "cmake_project",
]
