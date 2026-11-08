"""Compiler flags as practice requirements, for any compiled language: a flag is met by a CI command line that sets
it, by the build files' options that set it for the language and the compiler judged (`CompilerOption` facts, with
the conditions they need), or by whatever else a profile knows sets it (the flags of fpm's profiles).

A requirement only searches the commands that hold one of its hints: the literal start of each of the flag's
spellings, unless the flag names its own, and those of the build system settings that set it (`--werror`).
"""

import re
from collections.abc import Callable, Iterable, Iterator

from project_validator.facts import Facts
from project_validator.facts.build import CompilerOption
from project_validator.facts.practices import Evidence, Found, Requirement
from project_validator.tools.toolchains import (
    WARNING_LEVEL_HINTS,
    WARNINGS_AS_ERRORS_SETTING_HINTS,
    WARNINGS_AS_ERRORS_SETTINGS,
    Flag,
    warning_level_settings,
)

# What ends the literal start of a spelling.
_SPECIAL = re.compile(r"[\\()\[\]{}?*+|^$.]")


def literal_starts(spellings: str) -> tuple[str, ...] | None:
    """The literal start of each alternative of `spellings` (`-std=f` of `-std=f(?:2008|2018)`), or None when one
    has none to search for (`[/-]WX`)."""
    starts = []
    for alternative in _alternatives(spellings):
        start = alternative[: match.start()] if (match := _SPECIAL.search(alternative)) else alternative
        if len(start) < 2:
            return None
        starts.append(start)
    return tuple(dict.fromkeys(starts))


def _alternatives(spellings: str) -> Iterator[str]:
    """The top-level alternatives of a regular expression."""
    depth, start = 0, 0
    escaped = False
    for index, character in enumerate(spellings):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "|" and depth == 0:
            yield spellings[start:index]
            start = index + 1
    yield spellings[start:]


def flag_hints(flag: Flag) -> tuple[str, ...] | None:
    return flag.hints or literal_starts(flag.spellings)


def build_options(flag: Flag, languages: frozenset[str]) -> Found:
    """The build files' options that set `flag` for a build of one of `languages` with the compiler judged."""

    def found(facts: Facts, compiler: str | None) -> Iterator[Evidence]:
        for option in facts.of(CompilerOption):
            applies = option.applies
            for_compiler = compiler is None or compiler in applies.allowed("compilers")
            if for_compiler and applies.allowed("languages") & languages and flag.option.fullmatch(option.option):
                yield Evidence(option.origin.path, applies.requires)

    return found


def _all(found: tuple[Found, ...]) -> Found:
    def every(facts: Facts, compiler: str | None) -> Iterator[Evidence]:
        for each in found:
            yield from each(facts, compiler)

    return every


def flag_requirement(
    flag: Flag,
    languages: frozenset[str],
    *,
    configured: Iterable[str] = (),
    configured_hints: Iterable[str] = (),
    also: Iterable[Found] = (),
) -> Requirement:
    """`flag` for `languages`: on a command line (alone, or as an option's value: `--ghc-options=-Wall`), set by a
    build system setting a command line gives (`configured`, patterns, found by `configured_hints`), in the build
    files' options, or by what `also` finds."""
    configured, configured_hints = tuple(configured), tuple(configured_hints)
    if configured and not configured_hints:
        raise ValueError(f"{flag.name}: the settings that set it need hints to be searched for")
    runs = re.compile("|".join((flag.standalone.pattern, *configured)))
    hints = flag_hints(flag)
    return Requirement(
        name=flag.name,
        runs=runs,
        found=_all((build_options(flag, languages), *also)),
        hints=() if hints is None else (*hints, *configured_hints),
    )


type Also = Callable[[Flag], Iterable[Found]]
"""What else sets a flag, for each flag (the fpm profile a command builds with)."""


def _nothing(_flag: Flag) -> tuple[()]:
    return ()


def flag_requirements(
    flags: Iterable[Flag],
    languages: frozenset[str],
    *,
    configured: Callable[[Flag], Iterable[str]] = _nothing,
    configured_hints: Iterable[str] = (),
    also: Also = _nothing,
) -> tuple[Requirement, ...]:
    """A requirement for each of `flags` (see `flag_requirement`), `configured` giving the build system settings
    that set each, and `also` what else finds it."""
    return tuple(
        flag_requirement(
            flag, languages, configured=configured(flag), configured_hints=configured_hints, also=also(flag)
        )
        for flag in flags
    )


def warning_requirements(
    flags: Iterable[Flag], languages: frozenset[str], *, also: Also = _nothing
) -> tuple[Requirement, ...]:
    """A compiler's strict warning set as requirements: each flag on a command line, in the build files, or set by
    the Meson warning level that passes it."""
    return flag_requirements(
        flags, languages, configured=warning_level_settings, configured_hints=WARNING_LEVEL_HINTS, also=also
    )


def errors_requirements(
    flag: Flag | None, languages: frozenset[str], *, also: Also = _nothing
) -> tuple[Requirement, ...]:
    """Warnings as errors as a requirement: the compiler's `flag` (None when its flag is not known), or the build
    systems' settings that pass it (`--werror`, `COMPILE_WARNING_AS_ERROR`)."""
    if flag is None:
        return ()
    return flag_requirements(
        (flag,),
        languages,
        configured=lambda _flag: WARNINGS_AS_ERRORS_SETTINGS,
        configured_hints=WARNINGS_AS_ERRORS_SETTING_HINTS,
        also=also,
    )


__all__ = [
    "Also",
    "build_options",
    "errors_requirements",
    "flag_hints",
    "flag_requirement",
    "flag_requirements",
    "literal_starts",
    "warning_requirements",
]
