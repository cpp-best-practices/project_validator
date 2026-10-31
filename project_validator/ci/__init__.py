"""Pluggable CI providers: each one knows where its configuration lives and how to turn it into jobs."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from project_validator import yaml_support
from project_validator.core import Project
from project_validator.platforms import RUNNER_DEFAULT_COMPILERS, detect_compilers, detect_operating_systems


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """One CI job as it would run: a single OS, plus every compiler it builds with."""

    name: str
    os: str
    compilers: frozenset[str]
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


REDUCED_ACCURACY_NOTE = "reduced accuracy: PyYAML is not available, so CI files were scanned heuristically"


def find_ci_files(project: Project, providers: tuple[CiProvider, ...]) -> tuple[CiFile, ...]:
    return tuple(
        CiFile(provider=provider, path=path) for provider in providers for path in provider.config_files(project)
    )


def _job_with_compilers(name: str, os: str, compilers: list[str], *, heuristic: bool = False) -> Job:
    if compilers:
        return Job(name=name, os=os, compilers=frozenset(compilers), heuristic=heuristic)
    default = RUNNER_DEFAULT_COMPILERS.get(os)
    if default is None:
        return Job(name=name, os=os, compilers=frozenset(), heuristic=heuristic)
    return Job(name=name, os=os, compilers=frozenset({default}), default_compiler=True, heuristic=heuristic)


def build_job(name: str, os: str, *compiler_texts: str) -> Job:
    """Use the compilers named by the first text that names any, falling back to the runner's default."""
    compilers = next((found for text in compiler_texts if (found := detect_compilers(text))), [])
    return _job_with_compilers(name, os, compilers)


def heuristic_jobs(name: str, text: str) -> list[Job]:
    compilers = detect_compilers(text)
    operating_systems = detect_operating_systems(text) or ["unknown"]
    return [_job_with_compilers(name, os, compilers, heuristic=True) for os in operating_systems]


def _parse_file(project: Project, ci_file: CiFile, use_yaml: bool) -> tuple[list[Job], list[str]]:
    text = project.read_text(ci_file.path)
    parser = ci_file.provider.parse_yaml
    if parser is None:
        return heuristic_jobs(ci_file.path, text), [f"{ci_file.path}: {ci_file.provider.name} is scanned heuristically"]
    if not use_yaml or not yaml_support.available():
        return heuristic_jobs(ci_file.path, text), [REDUCED_ACCURACY_NOTE]
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        return heuristic_jobs(ci_file.path, text), [f"{ci_file.path}: invalid YAML ({error}), scanned heuristically"]
    return [replace(job, name=f"{ci_file.path}: {job.name}") for job in parser(document)], []


def parse_jobs(project: Project, ci_files: tuple[CiFile, ...], *, use_yaml: bool) -> CiAnalysis:
    jobs: list[Job] = []
    notes: list[str] = []
    for ci_file in ci_files:
        file_jobs, file_notes = _parse_file(project, ci_file, use_yaml)
        jobs.extend(file_jobs)
        notes.extend(file_notes)
    return CiAnalysis(jobs=tuple(jobs), notes=tuple(dict.fromkeys(notes)))
