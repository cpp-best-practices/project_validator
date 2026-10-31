from project_validator.ci import Job
from project_validator.core import Context, Result, check

MINIMUM_OPERATING_SYSTEMS = 2
MINIMUM_COMPILERS = 2
MINIMUM_COMBINATIONS = 3


def combinations(jobs: tuple[Job, ...]) -> set[tuple[str, str]]:
    return {(job.os, compiler) for job in jobs if job.os != "unknown" for compiler in job.compilers}


def _describe(job: Job) -> str:
    compilers = ", ".join(sorted(job.compilers)) or "no compiler"
    suffix = " (runner default)" if job.default_compiler else ""
    return f"{job.name}: {job.os} / {compilers}{suffix}"


def _shortfalls(operating_systems: set[str], compilers: set[str], pairs: set[tuple[str, str]]) -> list[str]:
    requirements = (
        ("operating systems", len(operating_systems), MINIMUM_OPERATING_SYSTEMS),
        ("compilers", len(compilers), MINIMUM_COMPILERS),
        ("OS/compiler combinations", len(pairs), MINIMUM_COMBINATIONS),
    )
    return [f"at least {minimum} {kind} (found {found})" for kind, found, minimum in requirements if found < minimum]


@check(name="platform-matrix", description="CI builds on several operating systems with several compilers")
def platform_matrix(context: Context) -> Result:
    if not context.ci_files:
        return Result.failed("no CI configuration found")

    analysis = context.ci_analysis
    pairs = combinations(analysis.jobs)
    operating_systems = {os for os, _ in pairs}
    compilers = {compiler for _, compiler in pairs}
    summary = (
        f"{len(operating_systems)} OS(es) ({', '.join(sorted(operating_systems)) or 'none'}), "
        f"{len(compilers)} compiler(s) ({', '.join(sorted(compilers)) or 'none'}), "
        f"{len(pairs)} combination(s)"
    )
    details = (*analysis.notes, *(_describe(job) for job in analysis.jobs))

    if shortfalls := _shortfalls(operating_systems, compilers, pairs):
        return Result.failed(f"CI covers {summary}; expected {', '.join(shortfalls)}", *details)
    return Result.passed(f"CI covers {summary}", *details)
