"""CMake as a build system: its build files, its build trees, and the build types its commands build."""

from __future__ import annotations

import re
from pathlib import Path

from project_validator.build_configurations import build_type_kinds
from project_validator.build_systems.cmake.conditions import LANGUAGE_NAMES
from project_validator.build_systems.cmake.syntax import CMakeSyntaxError, Invocation, Kind, invocations
from project_validator.build_systems.model import C_FAMILY, BuildSystem
from project_validator.facts import Command, resolved
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.dependencies import Lock, PackageManager

_BUILD_TYPE_DEFINITION = re.compile(r"^(?:-D\s*)?CMAKE_BUILD_TYPE(?::\w+)?=(.*)$")


def cmake_build_types(command: Command) -> frozenset[str]:
    """The build types a cmake or ctest command builds or tests: `-DCMAKE_BUILD_TYPE=` (or the `CMAKE_BUILD_TYPE`
    environment variable) when configuring, `--config` when building or installing, `-C` when testing."""
    argv = resolved(command)
    name = program(argv)
    if name == "ctest":
        return build_type_kinds(*option_values(argv, "-C", "--build-config"))
    if name != "cmake":
        return frozenset()
    defined = [match[1] for word in argv if (match := _BUILD_TYPE_DEFINITION.match(word))]
    configuring = not {"--build", "--install", "-E", "-P"} & set(argv)
    if configuring and not defined and "CMAKE_BUILD_TYPE" in command.env:
        defined = [command.env["CMAKE_BUILD_TYPE"]]
    return build_type_kinds(*defined, *option_values(argv, "--config"))


def cmake_configures(argv: tuple[str, ...]) -> bool:
    """Whether a cmake command configures a build tree, and so reads the CMake files."""
    excluded = ("--build", "--install", "-E", "-P", "--open", "--help", "--version")
    return program(argv) == "cmake" and not has_option(argv, *excluded)


def is_cmake_build_tree(directory: Path) -> bool:
    return (directory / "CMakeCache.txt").is_file()


# The keywords of project() that take a value; the languages are listed after the name or after LANGUAGES.
_PROJECT_KEYWORDS = frozenset({"VERSION", "DESCRIPTION", "HOMEPAGE_URL", "COMPAT_VERSION", "SPDX_LICENSE"})


def _project_languages(invocation: Invocation) -> frozenset[str] | None:
    """The languages a project() call enables: those it lists, C and C++ when it lists none, nothing for NONE; None
    when it names one with a variable, which is not evaluated here."""
    words = [argument.text for argument in invocation.arguments[1:] if argument.kind is not Kind.BRACKET]
    if any("${" in word for word in words):
        return None
    listed: list[str] = []
    listing, skip = True, False
    for word in words:
        if skip:
            skip = False
        elif word in _PROJECT_KEYWORDS:
            listing, skip = False, True
        elif word == "LANGUAGES":
            listing = True
        elif listing:
            listed.append(word)
    if not listed:
        return C_FAMILY
    return frozenset(LANGUAGE_NAMES[word] for word in listed if word in LANGUAGE_NAMES)


def _enabled(invocation: Invocation) -> frozenset[str] | None:
    if invocation.name == "project":
        return _project_languages(invocation)
    words = [argument.text for argument in invocation.arguments]
    if any("${" in word for word in words):
        return None
    return frozenset(LANGUAGE_NAMES[word] for word in words if word in LANGUAGE_NAMES)


def cmake_declared_languages(path: str, text: str) -> frozenset[str]:
    """The languages a CMake file enables, with project() and enable_language(). The top-level file always has a
    project: CMake adds `project(Project)`, which enables C and C++, when it calls none. A file that cannot be parsed,
    or that names a language with a variable, enables C and C++ as far as recognition can tell."""
    try:
        calls = [call for call in invocations(text) if call.name in ("project", "enable_language")]
    except CMakeSyntaxError:
        return C_FAMILY
    languages: set[str] = set()
    for call in calls:
        languages |= C_FAMILY if (enabled := _enabled(call)) is None else enabled
    if path == "CMakeLists.txt" and not any(call.name == "project" for call in calls):
        languages |= C_FAMILY
    return frozenset(languages)


CMAKE = BuildSystem(
    name="CMake",
    files=("CMakeLists.txt",),
    declared_languages=cmake_declared_languages,
    is_build_tree=is_cmake_build_tree,
    build_types=cmake_build_types,
)


# The dependency managers of CMake itself, for whatever it builds. Neither has a lockfile; each is suggested to a
# project that declares no dependencies.
CMAKE_PACKAGE_MANAGERS = tuple(
    PackageManager(name=name, languages=frozenset(LANGUAGE_NAMES.values()), lock=Lock.NEVER, suggested=True)
    for name in ("CPM", "FetchContent")
)
