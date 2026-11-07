"""C/C++ tests: registered with CTest in the CMake files (`enable_testing()`, then `add_test` or a `*_discover_tests`
call, as `project_validator.build_systems.cmake` reads them), or, with `--build`, listed by ctest after a real build.
ctest runs them."""

import json
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from project_validator.build_systems.cmake.build import cmake_configures
from project_validator.build_systems.model import C_FAMILY
from project_validator.core import Options, Project
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
from project_validator.facts.arguments import option_values, program
from project_validator.facts.testing import Probe, test_runner, tested
from project_validator.facts.tools import Definition, Run


class BuildError(Exception):
    pass


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 - argv list, no shell
    except OSError as error:
        raise BuildError(f"could not run {command[0]}: {error}") from error
    if completed.returncode != 0:
        last_lines = completed.stderr.strip().splitlines()[-5:]
        raise BuildError(f"`{' '.join(command)}` failed: {' | '.join(last_lines)}")
    return completed.stdout


# Multi-config generators (Visual Studio, Ninja Multi-Config) register tests per
# configuration, so ctest lists none unless asked for the configuration that was built.
BUILD_CONFIGURATION = "Debug"


def count_built_tests(root: Path, options: Options) -> int:
    with tempfile.TemporaryDirectory(prefix="project_validator_") as build:
        _run([options.cmake, "-S", str(root), "-B", build, f"-DCMAKE_BUILD_TYPE={BUILD_CONFIGURATION}"])
        _run([options.cmake, "--build", build, "--config", BUILD_CONFIGURATION])
        listing = json.loads(
            _run([options.ctest, "--test-dir", build, "-C", BUILD_CONFIGURATION, "--show-only=json-v1"])
        )
    return len(listing.get("tests", []))


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltTests(Fact):
    """How many tests ctest lists once the project is built (with `--build`)."""

    count: int


def _built_tests(project: Project, options: object) -> Iterator[Fact]:
    """With `--build`: configure and build the CMake project, and count the tests ctest lists; a build that cannot
    run is unknown."""
    if not isinstance(options, Options) or not project.exists("CMakeLists.txt"):
        return
    origin = Origin(path="CMakeLists.txt")
    try:
        yield BuiltTests(origin=origin, count=count_built_tests(project.root, options))
    except BuildError as error:
        yield Unknown(origin=origin, subject="the built tests", reason=str(error), hides="settings", tools=("ctest",))


BUILT_TESTS = Probe(name="ctest after a build", run=_built_tests)


def _registered(facts: Facts) -> Iterator[str]:
    """The files that define CTest tests: with `--build`, the project when ctest lists any; else the CMake files that
    register tests, once a CMake file enables CTest."""
    built = facts.of(BuiltTests)
    if built:
        yield from (found.origin.path for found in built if found.count)
        return
    if facts.where(Setting, tool="CTest", key="enables"):
        yield from (found.path for found in facts.where(Setting, tool="CTest", key="registers"))


def _ctest(command: Command, _facts: Facts) -> Run | None:
    """ctest, `cmake --build … --target test` (or RUN_TESTS), and `cmake --workflow`, whose presets run the tests."""
    argv = resolved(command)
    if program(argv) == "ctest":
        return tested()
    if program(argv) != "cmake":
        return None
    if "--workflow" in argv:
        return tested()
    targets = [] if cmake_configures(argv) else option_values(argv, "--target", "-t")
    return tested() if {"test", "RUN_TESTS"} & set(targets) else None


CTEST = test_runner(
    name="ctest",
    languages=C_FAMILY,
    how="ctest",
    runs=_ctest,
    tests=Definition(
        found=_registered,
        default=False,
        from_test_units=True,
        describe="tests registered with CTest (enable_testing(), then add_test or a *_discover_tests call)",
    ),
    reads=("CMake",),
)
