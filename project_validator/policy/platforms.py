"""The platform policies: CI runs on several OSes with several toolchains (`platform-matrix`), and a compiled
language's CI builds each of its platforms in Debug and Release, each with and without sanitizers
(`ci-build-types`)."""

from __future__ import annotations

from project_validator.build_configurations import BuildConfiguration
from project_validator.core import Result
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
            (f"OS/{answer.axis.noun} combinations", len(answer.platforms), MINIMUM_COMBINATIONS),
        )
        if answer.axis.operating_systems
        else (toolchain_requirement,)
    )
    return [f"at least {minimum} {kind} (found {found})" for kind, found, minimum in requirements if found < minimum]


def judge_matrix(answer: PlatformAnswer, *, allow_unknown: bool = False) -> Result:
    """Two OSes, two toolchains and three combinations of them pass; fewer fail. For an axis the OS is no part of (a
    database's engine versions), two toolchains pass, whatever runs them."""
    del allow_unknown  # what CI was read only heuristically is noted, not unknown
    if answer.answer is Answer.NO:
        return Result.failed(NO_CI)
    operating_systems = {os for (os, _), _ in answer.platforms}
    toolchains = {toolchain for (_, toolchain), _ in answer.platforms}
    noun = answer.axis.noun
    found = f"{len(toolchains)} {noun}(s) ({', '.join(sorted(toolchains)) or 'none'})"
    summary = (
        f"{len(operating_systems)} OS(es) ({', '.join(sorted(operating_systems)) or 'none'}), {found}, "
        f"{len(answer.platforms)} combination(s)"
        if answer.axis.operating_systems
        else f"{found}, whatever the OS"
    )
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


def judge_build_types(answer: PlatformAnswer, *, allow_unknown: bool = False) -> Result:
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
