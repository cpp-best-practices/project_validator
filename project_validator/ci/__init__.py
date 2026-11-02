"""Pluggable CI providers: each one knows where its configuration lives and how to turn it into jobs."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from project_validator import yaml_support
from project_validator.build_configurations import BuildConfiguration, detect_configurations
from project_validator.core import Project
from project_validator.platforms import (
    RUNNER_DEFAULT_COMPILERS,
    Toolchain,
    detect_compilers,
    detect_operating_systems,
    detect_toolchains,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """One CI job as it would run: a single OS, plus every compiler, toolchain and build configuration it uses."""

    name: str
    os: str
    compilers: frozenset[str]
    configurations: frozenset[BuildConfiguration] = frozenset()
    toolchains: frozenset[Toolchain] = frozenset()
    default_compiler: bool = False
    heuristic: bool = False


type YamlParser = Callable[[object], list[Job]]


@dataclass(frozen=True, slots=True, kw_only=True)
class CiProvider:
    name: str
    files: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".yml", ".yaml")
    parse_yaml: YamlParser | None = None

    def config_files(self, project: Project) -> list[str]:
        found = [path for path in self.files if project.exists(path)]
        for directory in self.directories:
            found.extend(project.files_in(directory, self.suffixes))
        return found


@dataclass(frozen=True, slots=True, kw_only=True)
class CiFile:
    provider: CiProvider
    path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CiAnalysis:
    jobs: tuple[Job, ...]
    notes: tuple[str, ...]


def find_ci_files(project: Project, providers: tuple[CiProvider, ...]) -> tuple[CiFile, ...]:
    return tuple(
        CiFile(provider=provider, path=path) for provider in providers for path in provider.config_files(project)
    )


def _job_with_compilers(
    name: str,
    os: str,
    compilers: list[str],
    configurations: set[BuildConfiguration],
    toolchains: frozenset[Toolchain],
    *,
    heuristic: bool = False,
) -> Job:
    found = frozenset(configurations)
    default = None if compilers else RUNNER_DEFAULT_COMPILERS.get(os)
    return Job(
        name=name,
        os=os,
        compilers=frozenset(compilers) if default is None else frozenset({default}),
        configurations=found,
        toolchains=toolchains,
        default_compiler=default is not None,
        heuristic=heuristic,
    )


def build_job(name: str, os: str, *texts: str) -> Job:
    """Use the compilers named by the first text that names any, falling back to the runner's default."""
    compilers = next((found for text in texts if (found := detect_compilers(text))), [])
    return _job_with_compilers(name, os, compilers, detect_configurations(*texts), detect_toolchains(*texts))


def heuristic_jobs(name: str, text: str) -> list[Job]:
    compilers = detect_compilers(text)
    configurations = detect_configurations(text)
    toolchains = detect_toolchains(text)
    operating_systems = detect_operating_systems(text) or ["unknown"]
    return [
        _job_with_compilers(name, os, compilers, configurations, toolchains, heuristic=True)
        for os in operating_systems
    ]


def _parse_file(project: Project, ci_file: CiFile) -> tuple[list[Job], list[str]]:
    text = project.read_text(ci_file.path)
    parser = ci_file.provider.parse_yaml
    if parser is None:
        return heuristic_jobs(ci_file.path, text), [f"{ci_file.path}: {ci_file.provider.name} is scanned heuristically"]
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        return heuristic_jobs(ci_file.path, text), [f"{ci_file.path}: invalid YAML ({error}), scanned heuristically"]
    return [replace(job, name=f"{ci_file.path}: {job.name}") for job in parser(document)], []


def parse_jobs(project: Project, ci_files: tuple[CiFile, ...]) -> CiAnalysis:
    jobs: list[Job] = []
    notes: list[str] = []
    for ci_file in ci_files:
        file_jobs, file_notes = _parse_file(project, ci_file)
        jobs.extend(file_jobs)
        notes.extend(file_notes)
    return CiAnalysis(jobs=tuple(jobs), notes=tuple(dict.fromkeys(notes)))
