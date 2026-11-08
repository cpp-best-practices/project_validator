"""Pluggable CI providers: each one knows where its configuration lives and how to turn it into jobs."""

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

from project_validator import yaml_support
from project_validator.build_configurations import BuildConfiguration, sanitizers_enabled
from project_validator.core import Project
from project_validator.ecosystems import build_systems
from project_validator.facts import (
    ActionStep,
    CiConfiguration,
    CiJob,
    Command,
    Fact,
    Facts,
    Origin,
    StepReference,
    Unknown,
    collected,
    resolved,
)
from project_validator.facts.expansion import script_facts
from project_validator.facts.jobs import Job, Toolchain
from project_validator.platforms import (
    RUNNER_DEFAULT_COMPILERS,
    detect_compilers,
    detect_ecosystems,
    detect_operating_systems,
    detect_toolchains,
)
from project_validator.text import Pattern

# Facts from a parsed configuration document at a path (see `project_validator.facts`).
# Reads another configuration file of the project (a reusable workflow, an included file), or None.
type Load = Callable[[str], object | None]
type FactExtractor = Callable[[str, object, Load], Iterable[Fact]]


@dataclass(frozen=True, slots=True, kw_only=True)
class CiProvider:
    name: str
    files: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".yml", ".yaml")
    # The tools that lint this provider's configuration when CI (or a pre-commit hook) runs them, and how to add one.
    linters: tuple[Pattern, ...] = ()
    lint_hint: str = ""
    # The status badge images this provider serves for a README.
    badges: tuple[Pattern, ...] = ()
    # The reusable steps (`owner/repo@ref`) a parsed configuration document uses, for providers that have them.
    step_references: Callable[[object], list[str]] | None = None
    facts: FactExtractor | None = None
    # Whether a configuration file's text shows the provider is used, for a file that may exist without it (a
    # `.pre-commit-config.yaml` is pre-commit.ci's only with a `ci:` section).
    recognises: Callable[[str], bool] | None = None

    def config_files(self, project: Project) -> list[str]:
        found = [path for path in self.files if project.exists(path)]
        for directory in self.directories:
            found.extend(project.files_in(directory, self.suffixes))
        recognises = self.recognises
        return found if recognises is None else [path for path in found if recognises(project.read_text(path))]


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
    job: CiJob,
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
        origin=job.origin,
        job=job.id,
        name=name,
        os=os,
        compilers=frozenset(compilers) if default is None else frozenset({default}),
        configurations=found,
        toolchains=toolchains,
        ecosystems=ecosystems,
        default_compiler=default is not None,
        heuristic=heuristic,
    )


def _enables(value: str) -> bool:
    """Whether an action input's value is known and switches something on (`vcvarsall: false` does not)."""
    return "${{" not in value and value.strip().lower() not in ("", "false", "off", "no", "0")


def _evidence(job: CiJob, facts: Iterable[Command | ActionStep]) -> str:
    """What a job shows about the tools it uses: its image, environment, the commands it runs (with the variables
    its environment defines in place) and the actions it uses with the inputs that are known and switched on.

    Step names and conditions, and inputs still holding an expression, show nothing about what runs.
    """
    lines = [f"image: {job.image}"] if job.image else []
    lines += [f"{name}: {value}" for name, value in job.env.items()]
    for fact in facts:
        if isinstance(fact, ActionStep):
            lines.append(f"uses: {fact.uses}")
            lines += [f"{name}: {value}" for name, value in fact.inputs.items() if _enables(value)]
        else:
            assignments = (f"{name}={value}" for name, value in fact.env.items() if job.env.get(name) != value)
            lines.append(" ".join((*assignments, *resolved(fact))))
    return "\n".join(lines)


def _configurations(commands: Iterable[Command], evidence: str) -> set[BuildConfiguration]:
    """The build configurations a job's commands build, as each build system reads its own commands."""
    readers = [system.build_types for system in build_systems() if system.build_types is not None]
    types = {found for command in commands for read in readers for found in read(command)}
    sanitizers = sanitizers_enabled((evidence,))
    return {BuildConfiguration(build_type=build_type, sanitizers=sanitizers) for build_type in types}


def _decoded(value: str) -> object:
    """A matrix value as it was written: one that is a list or a mapping is held as JSON."""
    if value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _matrix_text(matrix: Mapping[str, str]) -> str:
    """A job's matrix values as JSON, with those that are objects in place rather than JSON within JSON (so that
    `versions: {ghc: "9.6"}` reads `"ghc": "9.6"`)."""
    return json.dumps({key: _decoded(value) for key, value in matrix.items()})


def _job(job: CiJob, facts: tuple[Command | ActionStep, ...], project: Project) -> Job:
    """A job as the checks see it. A parsed job's compilers and toolchains are named by its matrix values first,
    then by what it runs; a heuristic job's by the whole file."""
    commands = [fact for fact in facts if isinstance(fact, Command)]
    evidence = _evidence(job, facts)
    texts = (project.read_text(job.origin.path),) if job.heuristic else (_matrix_text(job.matrix), evidence)
    compilers = next((found for text in texts if (found := detect_compilers(text))), [])
    return _job_with_compilers(
        job,
        f"{job.origin.path}: {job.name}" if not job.heuristic else job.origin.path,
        job.os,
        compilers,
        _configurations(commands, evidence),
        detect_toolchains(*texts),
        detect_ecosystems(*texts),
        heuristic=job.heuristic,
    )


def job_facts(facts: Facts, project: Project) -> Iterator[Job]:
    """The CI jobs that build the project, each with what it builds and runs on, from what it runs."""
    by_job: dict[str, list[Command | ActionStep]] = {}
    for fact in facts:
        if isinstance(fact, (Command, ActionStep)):
            by_job.setdefault(fact.job, []).append(fact)
    return (_job(job, tuple(by_job.get(job.id, ())), project) for job in facts.of(CiJob) if job.builds)


def ci_analysis(facts: Facts) -> CiAnalysis:
    """The CI jobs that build the project (see `job_facts`), and what was read only heuristically."""
    notes = (f"{fact.origin.path}: {fact.reason}" for fact in facts.of(Unknown) if fact.subject == _JOBS)
    return CiAnalysis(jobs=facts.of(Job), notes=tuple(dict.fromkeys(notes)))


def strings(value: object) -> dict[str, str]:
    """A YAML mapping of names to scalars (an `env:` or `with:` block) as strings; anything else as nothing."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item).lower() if isinstance(item, bool) else str(item) for key, item in value.items()}


_JOBS = "the jobs and commands"
# A line of configuration that is not parsed: list markers and a leading `key:` are not part of its command.
_CONFIGURATION_LINE = re.compile(r"^\s*(?:-\s+)?(?:[\w.-]+:\s*)?(?P<value>.*?)\s*$")


def _heuristic_facts(ci_file: CiFile, text: str, reason: str) -> Iterator[Fact]:
    """Configuration that is not parsed: one job per OS it names, running each line that could be a command."""
    origin = Origin(path=ci_file.path)
    operating_systems = detect_operating_systems(text) or ["unknown"]
    lines = (match["value"].strip("'\"") for line in text.splitlines() if (match := _CONFIGURATION_LINE.match(line)))
    script = "\n".join(line for line in lines if line and line not in ("|", ">", "|-", ">-"))
    for os in operating_systems:
        identity = ci_file.path if len(operating_systems) == 1 else f"{ci_file.path}[{os}]"
        yield CiJob(
            origin=origin, id=identity, provider=ci_file.provider.name, name=ci_file.path, os=os, heuristic=True
        )
        yield from (fact for fact in script_facts(script, job=identity, origin=origin) if isinstance(fact, Command))
    yield Unknown(origin=origin, subject=_JOBS, reason=reason, hides="jobs")


def _file_facts(project: Project, ci_file: CiFile) -> Iterator[Fact]:
    provider = ci_file.provider
    text = project.read_text(ci_file.path)
    if provider.facts is None:
        yield from _heuristic_facts(ci_file, text, f"{provider.name} is scanned heuristically")
        return
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        yield from _heuristic_facts(ci_file, text, f"invalid YAML ({error}), scanned heuristically")
        return
    yield from provider.facts(ci_file.path, document, _loader(project))
    if provider.step_references is not None:
        origin = Origin(path=ci_file.path)
        references = dict.fromkeys(provider.step_references(document))
        yield from (StepReference(origin=origin, reference=reference) for reference in references)


def _loader(project: Project) -> Load:
    def load(path: str) -> object | None:
        if not project.exists(path):
            return None
        try:
            return yaml_support.load(project.read_text(path))
        except yaml_support.YamlError:
            return None

    return load


def ci_facts(project: Project, ci_files: tuple[CiFile, ...]) -> Facts:
    """What the CI configuration shows: its files, its jobs, and the commands and reusable steps each one runs."""
    files = (CiConfiguration(origin=Origin(path=ci_file.path), provider=ci_file.provider.name) for ci_file in ci_files)
    return collected((files, *(_file_facts(project, ci_file) for ci_file in ci_files)))
