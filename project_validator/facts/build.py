"""What a project's build files set: compiler options and build settings, each with the builds it applies to.

A build file sets an option for some builds only: those with one compiler (`if(MSVC)`), on one platform, in one
configuration (`$<CONFIG:Debug>`), for one language, or behind a switch the build cannot decide (`option(ENABLE_X)`,
a compiler check). Each build system turns its conditions into a `Condition` (see `project_validator.facts.conditions`);
facts hold one `Applies` each, a disjunct of it: an option set under a condition with two disjuncts is two facts.
"""

import dataclasses
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import product

from project_validator.facts import Fact, Origin
from project_validator.facts.conditions import DIMENSIONS, OTHER, Condition, both, only, paths


@dataclass(frozen=True, slots=True, kw_only=True)
class Applies:
    """The builds something applies to: those whose compiler, platform, configuration and language are allowed
    (None allows every value), and in which each of `requires` holds ("ENABLE_WARNINGS", "NOT WIN32")."""

    compilers: frozenset[str] | None = None
    platforms: frozenset[str] | None = None
    configurations: frozenset[str] | None = None
    languages: frozenset[str] | None = None
    requires: frozenset[str] = frozenset()

    def allowed(self, dimension: str) -> frozenset[str]:
        values = getattr(self, dimension)
        return frozenset(DIMENSIONS[dimension]) if values is None else values

    @property
    def unconditional(self) -> bool:
        """Whether the build decides it alone: it requires nothing the build system cannot decide."""
        return not self.requires

    def as_dict(self) -> dict[str, object]:
        """JSON-ready: each dimension that is restricted, as its members, or, for a set open to every value not named
        (`if(NOT MSVC)` holds for a compiler named later too), as what it leaves out: `all but msvc`."""
        found: dict[str, object] = {}
        for dimension in DIMENSIONS:
            values: frozenset[str] | None = getattr(self, dimension)
            if values is None:
                continue
            left_out = sorted(set(DIMENSIONS[dimension]) - values)
            found[dimension] = f"all but {', '.join(left_out)}" if OTHER in values and left_out else sorted(values)
        if self.requires:
            found["requires"] = sorted(self.requires)
        return found


def _applies(path: Iterable[tuple[str, frozenset[str]]]) -> Applies:
    allowed: dict[str, frozenset[str]] = {}
    requires: set[str] = set()
    for dimension, values in path:
        if dimension == "requires":
            requires |= values
        else:
            allowed[dimension] = allowed.get(dimension, values) & values
    return Applies(
        compilers=allowed.get("compilers"),
        platforms=allowed.get("platforms"),
        configurations=allowed.get("configurations"),
        languages=allowed.get("languages"),
        requires=frozenset(requires),
    )


def _merged(first: Applies, second: Applies) -> Applies | None:
    """One `Applies` for the builds either applies to, when they differ in the values of one dimension only."""
    if first.requires != second.requires:
        return None
    different = [dimension for dimension in DIMENSIONS if first.allowed(dimension) != second.allowed(dimension)]
    if len(different) != 1:
        return None
    union: frozenset[str] | None = first.allowed(different[0]) | second.allowed(different[0])
    if union == frozenset(DIMENSIONS[different[0]]):
        union = None
    return dataclasses.replace(first, **{different[0]: union})  # type: ignore[arg-type]


def _simpler(found: list[Applies]) -> list[Applies] | None:
    for first, second in product(found, found):
        if first is not second and (union := _merged(first, second)) is not None:
            return [*(applies for applies in found if applies is not first and applies is not second), union]
    return None


def disjuncts(condition: Condition) -> tuple[Applies, ...]:
    """`condition` written out as few `Applies` as merging those that differ in one dimension gives."""
    found = list(dict.fromkeys(_applies(path) for path in paths(condition)))
    while (step := _simpler(found)) is not None:
        found = step
    return tuple(found)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompilerOption(Fact):
    """A compiler option a build file sets (a definition written `-DNAME=value`), or with `linking` a linker option,
    for the builds `applies` names; `target` is the target it is set on (None: every target the build file defines,
    and those below it)."""

    build_system: str
    option: str
    applies: Applies
    target: str | None = None
    linking: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildSetting(Fact):
    """A setting of the build system (`CMAKE_CXX_EXTENSIONS`, a target's `COMPILE_WARNING_AS_ERROR`, Meson's
    `werror`) and its value, for the builds `applies` names. A `default` is the value an option or cache variable takes
    unless the build is configured with another."""

    build_system: str
    name: str
    value: str
    applies: Applies
    target: str | None = None
    default: bool = False


def implied_options(
    origin: Origin,
    build_system: str,
    by_compiler: Iterable[tuple[frozenset[str], tuple[str, ...]]],
    builds: Condition,
    target: str | None = None,
) -> Iterator[CompilerOption]:
    """The options a build system's setting passes each compiler (CMake's `COMPILE_WARNING_AS_ERROR` passes GCC
    `-Werror` and MSVC `/WX`), in `builds`."""
    for compilers, options in by_compiler:
        for applies in disjuncts(both(builds, only("compilers", compilers))):
            for option in options:
                yield CompilerOption(
                    origin=origin, build_system=build_system, option=option, applies=applies, target=target
                )


__all__ = ["Applies", "BuildSetting", "CompilerOption", "disjuncts", "implied_options"]
