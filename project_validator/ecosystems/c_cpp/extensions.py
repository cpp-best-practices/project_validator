"""C and C++ compiled as standardised, without the compilers' extensions (`-std=c++20`, not `-std=gnu++20`): with
CMake, `CMAKE_<LANG>_EXTENSIONS` off for the whole build (in the CMake files, a preset or on the command line) or a
target's `<LANG>_EXTENSIONS` off; with Meson, a standard `cpp_std` (`c_std`)."""

import re
from collections.abc import Callable, Iterator
from pathlib import PurePosixPath

from project_validator.build_systems.cmake.conditions import constant
from project_validator.build_systems.cmake.presets import PRESET_FILES
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts
from project_validator.facts.build import BuildSetting
from project_validator.facts.practices import Evidence, Found, Practice, PracticeName, Requirement, Wording, always
from project_validator.facts.structure import SourceFile

_FALSE = r"(?i:OFF|FALSE|NO|N|0)\b"


def _settings(build_system: str, name: str, *, target: bool, preset: bool | None = None, value: str = "") -> Found:
    """The build settings called `name` of `build_system`, on a target or the whole build (in a preset or not), whose
    value is false (by default) or matches `value`."""

    def found(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
        for setting in facts.where(BuildSetting, build_system=build_system, name=name):
            in_preset = PurePosixPath(setting.origin.path).name in PRESET_FILES
            off = re.fullmatch(value, setting.value) if value else constant(setting.value) is False
            if off and (setting.target is not None) == target and preset in (None, in_preset):
                yield Evidence(setting.origin.path, setting.applies.requires)

    return found


def _sources_of(language: str) -> Callable[[Facts], str | None]:
    """A C/C++ project counts both languages; one whose sources are all in the other does not compile `language`."""

    def skipped(facts: Facts) -> str | None:
        languages = {source.language for source in facts.of(SourceFile)} & C_FAMILY
        return f"no {language} sources are compiled" if languages and language not in languages else None

    return skipped


def _requirements(cmake: str, std: str, standard: str, example: str) -> tuple[Requirement, ...]:
    """CMake's settings, for the whole build (in its files, on the command line, in a preset) or a target, and Meson's
    standard option."""
    return (
        Requirement(
            name=f"set(CMAKE_{cmake}_EXTENSIONS OFF)",
            found=_settings("CMake", f"CMAKE_{cmake}_EXTENSIONS", target=False, preset=False),
        ),
        Requirement(
            name=f"-DCMAKE_{cmake}_EXTENSIONS=OFF", runs=re.compile(rf"-DCMAKE_{cmake}_EXTENSIONS(?::BOOL)?={_FALSE}")
        ),
        Requirement(
            name=f"CMAKE_{cmake}_EXTENSIONS OFF in a preset",
            found=_settings("CMake", f"CMAKE_{cmake}_EXTENSIONS", target=False, preset=True),
        ),
        Requirement(name=f"{cmake}_EXTENSIONS OFF", found=_settings("CMake", f"{cmake}_EXTENSIONS", target=True)),
        Requirement(
            name=f"{std}={example}",
            runs=re.compile(rf"(?<![\w-])(?:-D\s*)?{std}\s*=\s*{standard}(?![\w+])"),
            found=_settings("Meson", std, target=False, value=standard),
        ),
    )


def _practice(language: str, cmake: str, std: str, standard: str, example: str) -> Practice:
    """The practice for `language`: CMake's `cmake` language name (CXX), Meson's `std` option (cpp_std), the
    `standard` values of it that name no extensions, and an `example` of one."""
    global_setting = f"set(CMAKE_{cmake}_EXTENSIONS OFF)"
    requirements = _requirements(cmake, std, standard, example)
    return Practice(
        name=PracticeName.EXTENSIONS,
        languages=frozenset({language}),
        requirements=always(*requirements),
        any_one=True,
        reads=("CMake", "Meson"),
        skipped=_sources_of(language),
        words=Wording(
            kind=f"{language} standard settings",
            hint=f"{global_setting} (Meson: default_options: ['{std}={example}'])",
            passed=f"{language} compiler extensions are disabled with {{found}}",
            failed=f"{language} compiler extensions are never disabled",
            question=f"whether {language} compiler extensions are disabled",
            preferred=tuple(requirement.name for requirement in requirements if not requirement.name.startswith(cmake)),
            preference=f"consider {global_setting} so that every target has extensions disabled",
        ),
    )


CXX_EXTENSIONS = _practice("C++", "CXX", "cpp_std", r"c\+\+\w+", "c++20")
C_EXTENSIONS = _practice("C", "C", "c_std", r"c\d\w*", "c17")
