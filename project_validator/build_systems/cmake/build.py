"""CMake as a build system: its build files, its build trees, and the build types its commands build."""

import re
from pathlib import Path

from project_validator.build_configurations import build_type_kinds
from project_validator.build_systems.model import C_FAMILY, BuildSystem
from project_validator.facts import Command, resolved
from project_validator.facts.arguments import has_option, option_values, program

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


CMAKE = BuildSystem(
    name="CMake",
    files=("CMakeLists.txt",),
    languages=C_FAMILY,
    is_build_tree=is_cmake_build_tree,
    build_types=cmake_build_types,
)
