"""What a CI job builds or runs with, per ecosystem: compilers for C/C++, interpreter or toolchain versions else."""

from collections.abc import Mapping

from project_validator.ci import Job
from project_validator.ecosystems import Ecosystem, ToolchainAxis, rules_of

AXES: Mapping[Ecosystem, ToolchainAxis] = rules_of(ToolchainAxis)


def platforms(jobs: tuple[Job, ...], axis: ToolchainAxis) -> set[tuple[str, str]]:
    """Every (OS, toolchain) pair the jobs run on, leaving out jobs whose OS is unknown."""
    return {(job.os, toolchain) for job in jobs if job.os != "unknown" for toolchain in axis.of_job(job)}
