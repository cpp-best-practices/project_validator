"""How a C/C++ build is laid out for the people and tools that use it: in-source builds are prevented
(`out-of-source-build`), `compile_commands.json` is exported for clang-based tooling (`compile-commands`), and the tests
and developer-only settings are guarded for a consumer that builds the project as a subproject (`top-level-guard`).
Each is read from the build files: what an `if()` guards on is a `guard` setting the evaluators record, as written.
Meson needs no guard against in-source builds and always writes `compile_commands.json`; a Meson project passes
both."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.build_systems.cmake.conditions import constant
from project_validator.build_systems.cmake.presets import PRESET_FILES
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts, Setting
from project_validator.facts.build import BuildSetting
from project_validator.facts.practices import Evidence, Found, Practice, PracticeName, Requirement, Wording, always
from project_validator.facts.structure import BuildFile

BUILD_SYSTEMS = ("CMake", "Meson")
_TRUE = r"(?i:ON|TRUE|YES|Y|1)\b"
_DIRECTORY = r"(?:CMAKE(?:_CURRENT)?|PROJECT)"
_COMPARED = r"\W+(?:STREQUAL|PATH_EQUAL)\W+\$?\{?"
# The idioms: the source and binary directories compared (in-source builds); the project's being top level.
_IN_SOURCE = re.compile(
    rf"{_DIRECTORY}_SOURCE_DIR{_COMPARED}{_DIRECTORY}_BINARY_DIR|{_DIRECTORY}_BINARY_DIR{_COMPARED}{_DIRECTORY}_SOURCE_DIR"
)
_TOP_LEVEL = re.compile(r"IS_TOP_LEVEL\b")
_TOP_LEVEL_DIRECTORIES = re.compile(
    rf"CMAKE(?:_CURRENT)?_SOURCE_DIR{_COMPARED}(?:PROJECT|CMAKE)_SOURCE_DIR|PROJECT_SOURCE_DIR{_COMPARED}CMAKE_SOURCE_DIR"
)
_IS_SUBPROJECT = re.compile(r"\bis_subproject\s*\(")


def _guards(build_system: str, pattern: re.Pattern[str]) -> Found:
    """The `if()` conditions of `build_system`'s files that match `pattern`, as written."""

    def found(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
        for guard in facts.where(Setting, tool=build_system, key="guard"):
            if pattern.search(str(guard.value)):
                yield Evidence(guard.path)

    return found


def _on(name: str, *, preset: bool | None = None) -> Found:
    """CMake's variable `name` set to a true value for the whole build, in a preset or not."""

    def found(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
        for setting in facts.where(BuildSetting, build_system="CMake", name=name, target=None):
            in_preset = PurePosixPath(setting.origin.path).name in PRESET_FILES
            if constant(setting.value) and preset in (None, in_preset):
                yield Evidence(setting.origin.path, setting.applies.requires)

    return found


def _meson_build(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
    """A Meson build, which needs no telling: it builds out of source and writes compile_commands.json."""
    yield from (Evidence(build.origin.path) for build in facts.where(BuildFile, build_system="Meson"))


def _no_build_files(facts: Facts) -> str | None:
    """A project with no CMake or Meson build file (header-only, built by its users) has no build to lay out."""
    if any(build.build_system in BUILD_SYSTEMS for build in facts.of(BuildFile)):
        return None
    return "no CMake or Meson build files"


def _practice(name: str, requirements: tuple[Requirement, ...], words: Wording) -> Practice:
    return Practice(
        name=name,
        languages=C_FAMILY,
        requirements=always(*requirements),
        any_one=True,
        reads=BUILD_SYSTEMS,
        skipped=_no_build_files,
        words=words,
    )


OUT_OF_SOURCE = _practice(
    PracticeName.OUT_OF_SOURCE,
    (
        Requirement(name="a check that the source and binary directories differ", found=_guards("CMake", _IN_SOURCE)),
        Requirement(name="CMAKE_DISABLE_IN_SOURCE_BUILD", found=_on("CMAKE_DISABLE_IN_SOURCE_BUILD")),
        Requirement(name="CMAKE_DISABLE_SOURCE_CHANGES", found=_on("CMAKE_DISABLE_SOURCE_CHANGES")),
        Requirement(name="Meson, which builds out of source", found=_meson_build),
    ),
    Wording(
        kind="in-source build guards",
        searched="the build files",
        hint="compare CMAKE_SOURCE_DIR with CMAKE_BINARY_DIR and message(FATAL_ERROR) when they are equal "
        "(cmake_template's PreventInSourceBuilds.cmake)",
        passed="in-source builds are prevented by {found}",
        failed="in-source builds are not prevented",
        question="whether in-source builds are prevented",
        warns=True,
    ),
)
COMPILE_COMMANDS = _practice(
    PracticeName.COMPILE_COMMANDS,
    (
        Requirement(
            name="set(CMAKE_EXPORT_COMPILE_COMMANDS ON)", found=_on("CMAKE_EXPORT_COMPILE_COMMANDS", preset=False)
        ),
        Requirement(
            name="-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            runs=re.compile(rf"-DCMAKE_EXPORT_COMPILE_COMMANDS(?::BOOL)?={_TRUE}"),
            hints=("CMAKE_EXPORT_COMPILE_COMMANDS",),
        ),
        Requirement(
            name="CMAKE_EXPORT_COMPILE_COMMANDS ON in a preset", found=_on("CMAKE_EXPORT_COMPILE_COMMANDS", preset=True)
        ),
        Requirement(name="Meson, which writes it", found=_meson_build),
    ),
    Wording(
        kind="compile_commands.json exports",
        searched="the build files or CI configuration",
        hint="set(CMAKE_EXPORT_COMPILE_COMMANDS ON), so clang-tidy, clangd and IDEs can read the build",
        passed="compile_commands.json is exported with {found}",
        failed="compile_commands.json is not exported",
        question="whether compile_commands.json is exported",
        warns=True,
    ),
)
TOP_LEVEL_GUARD = _practice(
    PracticeName.TOP_LEVEL_GUARD,
    (
        Requirement(name="PROJECT_IS_TOP_LEVEL", found=_guards("CMake", _TOP_LEVEL)),
        Requirement(
            name="CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR", found=_guards("CMake", _TOP_LEVEL_DIRECTORIES)
        ),
        Requirement(name="meson.is_subproject()", found=_guards("Meson", _IS_SUBPROJECT)),
    ),
    Wording(
        kind="top-level guards",
        searched="the build files",
        hint="condition the tests and developer-only options on PROJECT_IS_TOP_LEVEL (Meson: meson.is_subproject()), "
        "so that the project works as a subproject through FetchContent, CPM or add_subdirectory",
        passed="developer-only settings are guarded by {found}",
        failed="nothing is guarded for use as a subproject",
        question="whether the tests and developer-only settings are guarded for use as a subproject",
        warns=True,
    ),
)
