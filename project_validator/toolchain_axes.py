"""What a CI job builds or runs with, per ecosystem: compilers for C/C++, interpreter or toolchain versions else."""

from collections.abc import Callable
from dataclasses import dataclass

from project_validator.ci import Job
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, Ecosystem
from project_validator.platforms import toolchain_versions


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolchainAxis:
    noun: str
    of_job: Callable[[Job], frozenset[str]]
    runner_default: Callable[[Job], bool]

    def plural(self) -> str:
        return f"{self.noun}s"


def _compilers(job: Job) -> frozenset[str]:
    return job.compilers


def _uses_runner_default_compiler(job: Job) -> bool:
    return job.default_compiler


def _python_versions(job: Job) -> frozenset[str]:
    return toolchain_versions(job.toolchains, "Python")


def _rust_toolchains(job: Job) -> frozenset[str]:
    return toolchain_versions(job.toolchains, "Rust")


def _never(_: Job) -> bool:
    return False


AXES: dict[Ecosystem, ToolchainAxis] = {
    C_AND_CXX: ToolchainAxis(noun="compiler", of_job=_compilers, runner_default=_uses_runner_default_compiler),
    PYTHON: ToolchainAxis(noun="Python version", of_job=_python_versions, runner_default=_never),
    RUST: ToolchainAxis(noun="Rust toolchain", of_job=_rust_toolchains, runner_default=_never),
}


def platforms(jobs: tuple[Job, ...], axis: ToolchainAxis) -> set[tuple[str, str]]:
    """Every (OS, toolchain) pair the jobs run on, leaving out jobs whose OS is unknown."""
    return {(job.os, toolchain) for job in jobs if job.os != "unknown" for toolchain in axis.of_job(job)}
