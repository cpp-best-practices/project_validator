"""C/C++ sanitizers: AddressSanitizer and UndefinedBehaviorSanitizer are used in at least one configuration of the
build, whatever the compiler: `-fsanitize=address,undefined` (MSVC's `/fsanitize=address`) among the build files'
options, on a CI command line, behind an option CI turns on (cmake_template's `ENABLE_SANITIZER_ADDRESS` and
`ENABLE_SANITIZER_UNDEFINED_BEHAVIOR`, with or without a project prefix), or Meson's `b_sanitize`. ThreadSanitizer and
MemorySanitizer are not asked: they exclude the other two in one build."""

from __future__ import annotations

import re
from collections.abc import Iterator

from project_validator.build_systems.cmake.conditions import constant
from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Facts
from project_validator.facts.build import BuildSetting
from project_validator.facts.flags import flag_requirement
from project_validator.facts.practices import Evidence, Found, Practice, PracticeName, Wording, always
from project_validator.tools.toolchains import Flag

_LIST = r"(?:[\w-]+,)*{}(?:,[\w-]+)*"
ASAN = Flag("AddressSanitizer", rf"-fsanitize={_LIST.format('address')}|/fsanitize=address", hints=("sanitize",))
UBSAN = Flag("UndefinedBehaviorSanitizer", rf"-fsanitize={_LIST.format('undefined')}", hints=("sanitize",))
_TRUE = r"(?i:ON|TRUE|YES|Y|1)\b"


def _option_names(sanitizer: str) -> re.Pattern[str]:
    """cmake_template's option for a sanitizer, with or without the project's prefix (`myproject_`)."""
    return re.compile(rf"(?:^|_)ENABLE_SANITIZER_{sanitizer}$")


_OPTIONS = {ASAN.name: _option_names("ADDRESS"), UBSAN.name: _option_names("UNDEFINED(?:_BEHAVIOR)?")}
_MESON_VALUES = {ASAN.name: "address", UBSAN.name: "undefined"}


def _configured(flag: Flag) -> tuple[str, ...]:
    """The settings a CI command line sets the sanitizer with: the option (`-Dmyproject_ENABLE_SANITIZER_ADDRESS=ON`)
    or Meson's `-Db_sanitize=address,undefined`."""
    option = _OPTIONS[flag.name].pattern.removeprefix("(?:^|_)").removesuffix("$")
    return (rf"\w*{option}(?::BOOL)?={_TRUE}", rf"b_sanitize={_LIST.format(_MESON_VALUES[flag.name])}\b")


def _settings(flag: Flag) -> tuple[Found]:
    """The build settings that turn the sanitizer on: the option defaulting to on, or `b_sanitize` naming it."""
    option, value = _OPTIONS[flag.name], _MESON_VALUES[flag.name]

    def found(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
        for setting in facts.of(BuildSetting):
            cmake = setting.build_system == "CMake" and option.search(setting.name) and constant(setting.value)
            meson = (
                setting.build_system == "Meson" and setting.name == "b_sanitize" and value in setting.value.split(",")
            )
            if cmake or meson:
                yield Evidence(setting.origin.path, setting.applies.requires)

    return (found,)


SANITIZERS = Practice(
    name=PracticeName.SANITIZERS,
    languages=C_FAMILY,
    requirements=always(
        *(
            flag_requirement(
                flag,
                C_FAMILY,
                configured=_configured(flag),
                configured_hints=("SANITIZER", "b_sanitize"),
                also=_settings(flag),
            )
            for flag in (ASAN, UBSAN)
        )
    ),
    reads=("CMake", "Meson"),
    words=Wording(
        kind="sanitizers",
        searched="the build files or CI configuration",
        hint="build with -fsanitize=address,undefined (MSVC: /fsanitize=address) in at least one configuration, "
        "behind an option CI turns on (Meson: -Db_sanitize=address,undefined)",
    ),
)
