"""Compiler flags as practice requirements, for any compiled language: a flag is met by a CI command line that sets
it, by the build files' options that set it for the language and the compiler judged (`CompilerOption` facts, with
the conditions they need), or by whatever else a profile knows sets it (the flags of fpm's profiles).

A requirement only searches the commands that hold one of its hints: the literal start of each of the flag's
spellings, unless the flag names its own, and those of the build system settings that set it (`--werror`).
"""

import re
from collections.abc import Iterable, Iterator

from project_validator.facts import Facts
from project_validator.facts.build import CompilerOption
from project_validator.facts.practices import Evidence, Found, Requirement
from project_validator.tools.toolchains import Flag

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


__all__ = ["build_options", "flag_hints", "flag_requirement", "literal_starts"]
