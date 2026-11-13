"""What CI builds with: each CI job as it would run, with the OS, compilers, toolchains and build configurations it
uses. The CI layer records these from the `CiJob` and `Command` facts; the platform questions and the profiles' axes
read them."""

from __future__ import annotations

from dataclasses import dataclass

from project_validator.build_configurations import BuildConfiguration
from project_validator.facts import Fact


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class Toolchain:
    """A language toolchain a CI job runs with, e.g. Python 3.14 or Rust nightly."""

    language: str
    version: str

    def __str__(self) -> str:
        return f"{self.language} {self.version}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Job(Fact):
    """One CI job (the `CiJob` whose id is `job`) as it would run: a single OS, plus every compiler, toolchain and
    build configuration it uses. A compiler is the runner's default (`default_compiler`) when the job names none."""

    job: str
    name: str
    os: str
    compilers: frozenset[str]
    configurations: frozenset[BuildConfiguration] = frozenset()
    toolchains: frozenset[Toolchain] = frozenset()
    # The labels of the ecosystems the job is seen building with or running (see `Ecosystem.used_by`).
    ecosystems: frozenset[str] = frozenset()
    # The images of the service containers the job runs beside itself (`postgres:16`): what a database project is
    # tested against.
    services: frozenset[str] = frozenset()
    default_compiler: bool = False
    heuristic: bool = False


__all__ = ["Job", "Toolchain"]
