from collections import defaultdict

from project_validator.build_configurations import BuildConfiguration
from project_validator.ci import Job
from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, RUST, check_each_ecosystem, languages_of
from project_validator.toolchain_axes import AXES, ToolchainAxis

REQUIRED_CONFIGURATIONS = frozenset(
    BuildConfiguration(build_type=build_type, sanitizers=sanitizers)
    for build_type in ("debug", "release")
    for sanitizers in (False, True)
)
REQUIREMENT = "build Debug and Release, each with and without sanitizers"

# Interpreted languages such as Python have no build types, so only compiled ecosystems are judged.
BUILT_AXES = {ecosystem: AXES[ecosystem] for ecosystem in (C_AND_CXX, RUST)}

type Platform = tuple[str, str]


def configurations_by_platform(jobs: tuple[Job, ...], axis: ToolchainAxis) -> dict[Platform, set[BuildConfiguration]]:
    found: defaultdict[Platform, set[BuildConfiguration]] = defaultdict(set)
    for job in jobs:
        if job.os == "unknown":
            continue
        for toolchain in axis.of_job(job):
            found[(job.os, toolchain)] |= job.configurations
    return dict(sorted(found.items()))


def _shortfall(platform: Platform, configurations: set[BuildConfiguration]) -> str | None:
    label = " / ".join(platform)
    if not configurations:
        return f"{label}: no build type specified"
    if missing := sorted(REQUIRED_CONFIGURATIONS - configurations):
        return f"{label}: missing {', '.join(map(str, missing))}"
    return None


def _built_everywhere(axis: ToolchainAxis, context: Context) -> Result:
    if not context.ci_files:
        return Result.failed("no CI configuration found")

    analysis = context.ci_analysis
    combinations = f"OS/{axis.noun} combination(s)"
    platforms = configurations_by_platform(analysis.jobs, axis)
    if not platforms:
        return Result.failed(f"no OS/{axis.noun} combination found in CI configuration", *analysis.notes)

    shortfalls = [found for platform, configs in platforms.items() if (found := _shortfall(platform, configs))]
    if shortfalls:
        message = f"{len(shortfalls)} of {len(platforms)} {combinations} do not {REQUIREMENT}"
        return Result.failed(message, *analysis.notes, *shortfalls)
    return Result.passed(f"all {len(platforms)} {combinations} {REQUIREMENT}", *analysis.notes)


@check(
    name="ci-build-types",
    description="CI builds Debug and Release, with and without sanitizers, everywhere",
    languages=languages_of(BUILT_AXES),
)
def ci_build_types(context: Context) -> Result:
    return check_each_ecosystem(context, BUILT_AXES, _built_everywhere)
