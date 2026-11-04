"""What a CI job builds or runs with, per ecosystem: compilers for C/C++, interpreter or toolchain versions else."""

from project_validator.ci import Job
from project_validator.ecosystems import ECOSYSTEMS, Ecosystem, ToolchainAxis

AXES: dict[Ecosystem, ToolchainAxis] = {ecosystem: ecosystem.axis for ecosystem in ECOSYSTEMS if ecosystem.axis}


def platforms(jobs: tuple[Job, ...], axis: ToolchainAxis) -> set[tuple[str, str]]:
    """Every (OS, toolchain) pair the jobs run on, leaving out jobs whose OS is unknown."""
    return {(job.os, toolchain) for job in jobs if job.os != "unknown" for toolchain in axis.of_job(job)}
