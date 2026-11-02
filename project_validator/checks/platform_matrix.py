from project_validator.ci import Job
from project_validator.core import Context, Result, check
from project_validator.ecosystems import check_each_ecosystem, languages_of
from project_validator.toolchain_axes import AXES, ToolchainAxis, platforms

MINIMUM_OPERATING_SYSTEMS = 2
MINIMUM_COMPILERS = 2
MINIMUM_COMBINATIONS = 3


def _describe(job: Job, axis: ToolchainAxis) -> str:
    toolchains = ", ".join(sorted(axis.of_job(job))) or f"no {axis.noun}"
    suffix = " (runner default)" if axis.runner_default(job) else ""
    return f"{job.name}: {job.os} / {toolchains}{suffix}"


def _shortfalls(
    axis: ToolchainAxis, operating_systems: set[str], toolchains: set[str], pairs: set[tuple[str, str]]
) -> list[str]:
    requirements = (
        ("operating systems", len(operating_systems), MINIMUM_OPERATING_SYSTEMS),
        (axis.plural(), len(toolchains), MINIMUM_COMPILERS),
        (f"OS/{axis.noun} combinations", len(pairs), MINIMUM_COMBINATIONS),
    )
    return [f"at least {minimum} {kind} (found {found})" for kind, found, minimum in requirements if found < minimum]


def _covered(axis: ToolchainAxis, context: Context) -> Result:
    if not context.ci_files:
        return Result.failed("no CI configuration found")

    analysis = context.ci_analysis
    pairs = platforms(analysis.jobs, axis)
    operating_systems = {os for os, _ in pairs}
    toolchains = {toolchain for _, toolchain in pairs}
    summary = (
        f"{len(operating_systems)} OS(es) ({', '.join(sorted(operating_systems)) or 'none'}), "
        f"{len(toolchains)} {axis.noun}(s) ({', '.join(sorted(toolchains)) or 'none'}), "
        f"{len(pairs)} combination(s)"
    )
    details = (*analysis.notes, *(_describe(job, axis) for job in analysis.jobs))

    if shortfalls := _shortfalls(axis, operating_systems, toolchains, pairs):
        return Result.failed(f"CI covers {summary}; expected {', '.join(shortfalls)}", *details)
    return Result.passed(f"CI covers {summary}", *details)


@check(
    name="platform-matrix",
    description="CI runs on several operating systems with several compilers (or interpreter/toolchain versions)",
    languages=languages_of(AXES),
)
def platform_matrix(context: Context) -> Result:
    return check_each_ecosystem(context, AXES, _covered)
