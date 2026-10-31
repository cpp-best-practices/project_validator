from collections import defaultdict

from project_validator.build_configurations import BuildConfiguration
from project_validator.ci import Job
from project_validator.core import Context, Result, check

REQUIRED_CONFIGURATIONS = frozenset(
    BuildConfiguration(build_type=build_type, sanitizers=sanitizers)
    for build_type in ("debug", "release")
    for sanitizers in (False, True)
)
REQUIREMENT = "build Debug and Release, each with and without sanitizers"

type Platform = tuple[str, str]


def configurations_by_platform(jobs: tuple[Job, ...]) -> dict[Platform, set[BuildConfiguration]]:
    found: defaultdict[Platform, set[BuildConfiguration]] = defaultdict(set)
    for job in jobs:
        if job.os == "unknown":
            continue
        for compiler in job.compilers:
            found[(job.os, compiler)] |= job.configurations
    return dict(sorted(found.items()))


def _shortfall(platform: Platform, configurations: set[BuildConfiguration]) -> str | None:
    label = " / ".join(platform)
    if not configurations:
        return f"{label}: no build type specified"
    if missing := sorted(REQUIRED_CONFIGURATIONS - configurations):
        return f"{label}: missing {', '.join(map(str, missing))}"
    return None


@check(name="ci-build-types", description="CI builds Debug and Release, with and without sanitizers, everywhere")
def ci_build_types(context: Context) -> Result:
    if not context.ci_files:
        return Result.failed("no CI configuration found")

    analysis = context.ci_analysis
    platforms = configurations_by_platform(analysis.jobs)
    if not platforms:
        return Result.failed("no OS/compiler combination found in CI configuration", *analysis.notes)

    shortfalls = [found for platform, configs in platforms.items() if (found := _shortfall(platform, configs))]
    if shortfalls:
        message = f"{len(shortfalls)} of {len(platforms)} OS/compiler combination(s) do not {REQUIREMENT}"
        return Result.failed(message, *analysis.notes, *shortfalls)
    return Result.passed(f"all {len(platforms)} OS/compiler combination(s) {REQUIREMENT}", *analysis.notes)
