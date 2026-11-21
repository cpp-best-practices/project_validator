"""The platform policies: CI runs on several OSes with several toolchains (`platform-matrix`), and a compiled
language's CI builds each of its platforms in Debug and Release, each with and without sanitizers
(`ci-build-types`)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from project_validator.build_configurations import BuildConfiguration
from project_validator.core import Result
from project_validator.platforms import DEFAULT_VERSION
from project_validator.questions import Answer
from project_validator.questions.platforms import Platform, PlatformAnswer

MINIMUM_OPERATING_SYSTEMS = 2
MINIMUM_COMPILERS = 2
MINIMUM_COMBINATIONS = 3
REQUIRED_CONFIGURATIONS = frozenset(
    BuildConfiguration(build_type=build_type, sanitizers=sanitizers)
    for build_type in ("debug", "release")
    for sanitizers in (False, True)
)
REQUIREMENT = "build Debug and Release, each with and without sanitizers"
NO_CI = "no CI configuration found"


def _shortfalls(answer: PlatformAnswer, operating_systems: set[str], toolchains: set[str]) -> list[str]:
    toolchain_requirement = (answer.axis.plural(), len(toolchains), MINIMUM_COMPILERS)
    requirements = (
        (
            ("operating systems", len(operating_systems), MINIMUM_OPERATING_SYSTEMS),
            toolchain_requirement,
            (
                f"OS/{answer.axis.noun} combinations",
                len(_counted(platform for platform, _ in answer.platforms)),
                MINIMUM_COMBINATIONS,
            ),
        )
        if answer.axis.operating_systems
        else (toolchain_requirement,)
    )
    return [f"at least {minimum} {kind} (found {found})" for kind, found, minimum in requirements if found < minimum]


_SPELLING = re.compile(r"^[~^=v]+|(?:\.x|\.0)+$")


def _version(toolchain: str) -> str:
    """A toolchain's version as one spelling: `3.x` is `3`, `1.27.0` is `1.27`, `~1.27` is `1.27`."""
    label, _, version = toolchain.rpartition(" ")
    normal = _SPELLING.sub("", version) or version
    return f"{label} {normal}" if label else normal


def _counted(platforms: Iterable[Platform]) -> set[Platform]:
    """The platforms as counted: one per OS and version however the version is spelled (each kept as one of its
    spellings), and a job that pins no version ("default") left out where others do pin one: it adds none of its
    own."""
    spellings: dict[Platform, str] = {}
    for os, toolchain in sorted(platforms):
        spellings.setdefault((os, _version(toolchain)), toolchain)
    counted = {(os, toolchain) for (os, _), toolchain in spellings.items()}
    pinned = {platform for platform in counted if platform[1].rpartition(" ")[2] != DEFAULT_VERSION}
    return pinned or counted


def _uncounted(answer: PlatformAnswer, operating_systems: set[str]) -> str:
    """What the count leaves out that the detail lines show: the OSes whose jobs name no toolchain, and the jobs on a
    runner of unknown OS."""
    clauses = []
    if answer.axis.operating_systems and (idle := [os for os in answer.unversioned if os not in operating_systems]):
        clauses.append(f"jobs on {', '.join(idle)} set up no {answer.axis.noun}")
    if answer.unplaced:
        clauses.append(f"{answer.unplaced} job(s) run on runners of unknown OS")
    return "".join(f"; {clause}" for clause in clauses)


def judge_matrix(answer: PlatformAnswer, *, allow_unknown: bool) -> Result:
    """Two OSes, two toolchains and three combinations of them pass; fewer fail. For an axis the OS is no part of (a
    database's engine versions), two toolchains pass, whatever runs them."""
    del allow_unknown  # what CI was read only heuristically is noted, not unknown
    if answer.answer is Answer.NO:
        return Result.failed(NO_CI)
    counted = _counted(platform for platform, _ in answer.platforms)
    operating_systems = {os for os, _ in counted}
    toolchains = {toolchain for _, toolchain in counted}
    noun = answer.axis.noun
    found = f"{len(toolchains)} {noun}(s) ({', '.join(sorted(toolchains)) or 'none'})"
    summary = (
        f"{len(operating_systems)} OS(es) ({', '.join(sorted(operating_systems)) or 'none'}), {found}, "
        f"{len(counted)} combination(s)"
        if answer.axis.operating_systems
        else f"{found}, whatever the OS"
    )
    summary += _uncounted(answer, operating_systems)
    details = (*answer.notes, *answer.jobs)
    if shortfalls := _shortfalls(answer, operating_systems, toolchains):
        return Result.failed(f"CI covers {summary}; expected {', '.join(shortfalls)}", *details)
    return Result.passed(f"CI covers {summary}", *details)


def _shortfall(platform: Platform, configurations: frozenset[BuildConfiguration]) -> str | None:
    label = " / ".join(platform)
    if not configurations:
        return f"{label}: no build type specified"
    if missing := sorted(REQUIRED_CONFIGURATIONS - configurations):
        return f"{label}: missing {', '.join(map(str, missing))}"
    return None


def judge_build_types(answer: PlatformAnswer, *, allow_unknown: bool) -> Result:
    """Every platform building Debug and Release, with and without sanitizers, passes; any short of it fails."""
    del allow_unknown
    if answer.answer is Answer.NO:
        return Result.failed(NO_CI)
    combinations = f"OS/{answer.axis.noun} combination(s)"
    if not answer.platforms:
        return Result.failed(f"no OS/{answer.axis.noun} combination found in CI configuration", *answer.notes)
    shortfalls = [
        found for platform, configurations in answer.platforms if (found := _shortfall(platform, configurations))
    ]
    if shortfalls:
        message = f"{len(shortfalls)} of {len(answer.platforms)} {combinations} do not {REQUIREMENT}"
        return Result.failed(message, *answer.notes, *shortfalls)
    return Result.passed(f"all {len(answer.platforms)} {combinations} {REQUIREMENT}", *answer.notes)


__all__ = ["judge_build_types", "judge_matrix"]
