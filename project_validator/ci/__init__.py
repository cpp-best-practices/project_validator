"""Pluggable CI providers: each one knows where its configuration lives and how to turn it into jobs."""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace

from project_validator import yaml_support
from project_validator.build_configurations import BuildConfiguration, detect_configurations
from project_validator.core import Project
from project_validator.facts import NOTHING, CiJob, Command, Fact, Facts, Origin, Unknown, collected
from project_validator.facts.shell import ShellCommand, split_script
from project_validator.platforms import (
    RUNNER_DEFAULT_COMPILERS,
    Toolchain,
    detect_compilers,
    detect_ecosystems,
    detect_operating_systems,
    detect_toolchains,
)
from project_validator.text import Pattern


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """One CI job as it would run: a single OS, plus every compiler, toolchain and build configuration it uses."""

    name: str
    os: str
    compilers: frozenset[str]
    configurations: frozenset[BuildConfiguration] = frozenset()
    toolchains: frozenset[Toolchain] = frozenset()
    # The labels of the ecosystems the job is seen building with or running (see `Ecosystem.used_by`).
    ecosystems: frozenset[str] = frozenset()
    default_compiler: bool = False
    heuristic: bool = False


type YamlParser = Callable[[object], list[Job]]
# Facts from a parsed configuration document at a path (see `project_validator.facts`).
type FactExtractor = Callable[[str, object], Iterable[Fact]]


@dataclass(frozen=True, slots=True, kw_only=True)
class CiProvider:
    name: str
    files: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".yml", ".yaml")
    parse_yaml: YamlParser | None = None
    # The tools that lint this provider's configuration when CI (or a pre-commit hook) runs them, and how to add one.
    linters: tuple[Pattern, ...] = ()
    lint_hint: str = ""
    # The status badge images this provider serves for a README.
    badges: tuple[Pattern, ...] = ()
    # The reusable steps (`owner/repo@ref`) a parsed configuration document uses, for providers that have them.
    step_references: Callable[[object], list[str]] | None = None
    facts: FactExtractor | None = None

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
    ecosystems: frozenset[str],
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
        ecosystems=ecosystems,
        default_compiler=default is not None,
        heuristic=heuristic,
    )


def build_job(name: str, os: str, *texts: str) -> Job:
    """Use the compilers named by the first text that names any, falling back to the runner's default."""
    compilers = next((found for text in texts if (found := detect_compilers(text))), [])
    return _job_with_compilers(
        name, os, compilers, detect_configurations(*texts), detect_toolchains(*texts), detect_ecosystems(*texts)
    )


def heuristic_jobs(name: str, text: str) -> list[Job]:
    compilers = detect_compilers(text)
    configurations = detect_configurations(text)
    toolchains = detect_toolchains(text)
    ecosystems = detect_ecosystems(text)
    operating_systems = detect_operating_systems(text) or ["unknown"]
    return [
        _job_with_compilers(name, os, compilers, configurations, toolchains, ecosystems, heuristic=True)
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


def strings(value: object) -> dict[str, str]:
    """A YAML mapping of names to scalars (an `env:` or `with:` block) as strings; anything else as nothing."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item).lower() if isinstance(item, bool) else str(item) for key, item in value.items()}


def script_facts(
    script: str,
    *,
    job: str,
    origin: Origin,
    env: Mapping[str, str] = NOTHING,
    directory: str | None = None,
    condition: str | None = None,
    opaque: re.Pattern[str] | None = None,
) -> Iterator[Fact]:
    """The commands of a shell script a job runs; a line that cannot be split is recorded as unknown.

    `opaque` matches the expressions the CI service evaluates before the shell runs (see `split_script`).
    """
    for found in split_script(script, opaque):
        if isinstance(found, ShellCommand):
            yield Command(
                origin=origin,
                job=job,
                argv=found.argv,
                line=found.line,
                env={**env, **dict(found.env)},
                directory=directory,
                condition=condition,
            )
        else:
            yield Unknown(origin=origin, subject=f"the command {found.line!r}", reason=found.reason)


def _file_facts(project: Project, ci_file: CiFile) -> Iterable[Fact]:
    provider = ci_file.provider
    origin = Origin(path=ci_file.path)
    if provider.parse_yaml is None or provider.facts is None:
        return (
            CiJob(
                origin=origin, id=ci_file.path, provider=provider.name, name=ci_file.path, os="unknown", heuristic=True
            ),
            Unknown(
                origin=origin, subject="the jobs and commands", reason=f"{provider.name} configuration is not parsed"
            ),
        )
    try:
        document = yaml_support.load(project.read_text(ci_file.path))
    except yaml_support.YamlError as error:
        return (Unknown(origin=origin, subject="the jobs and commands", reason=f"invalid YAML ({error})"),)
    return provider.facts(ci_file.path, document)


def ci_facts(project: Project, ci_files: tuple[CiFile, ...]) -> Facts:
    """What the CI configuration shows: its jobs, and the commands and reusable steps each one runs."""
    return collected(_file_facts(project, ci_file) for ci_file in ci_files)
