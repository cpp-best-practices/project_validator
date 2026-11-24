"""CircleCI: `.circleci/config.yml` read as the jobs its workflows run and the commands of their steps (upstream #223).

A workflow's job entry runs a job of `jobs:` once, or once per combination of its `matrix: parameters:` (named
`job-value-...`), with its parameters: the job's defaults under the entry's own and the combination's; a config with
no workflows runs each job once. `<< parameters.x >>` and `<< pipeline.parameters.x >>` are replaced by their values.
The runner is the job's `docker` images (the first runs the steps; the others are its services), `machine` or
`macos` executor, or the named executor of `executors:` it uses. A `run` step runs in `/bin/bash -eo pipefail` (in
PowerShell on Windows) unless it names a `shell`; a step that runs in the `background` cannot fail the job. A command
of `commands:` is expanded with its parameters, `when` and `unless` steps are read as the steps they hold, and the
built-in steps (`checkout`, the caches, the workspace, the artifacts) run nothing of the project's. A command or job
of an orb is not read: it is unknown.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin, Unknown
from project_validator.facts.exit_status import STRICT, Shell, shell_of
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import CMD, POSIX, POWERSHELL, Dialect
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern

type _Path = tuple[str | int, ...]

_BUILT_IN_STEPS = frozenset(
    {"checkout", "setup_remote_docker", "save_cache", "restore_cache", "store_artifacts", "store_test_results"}
    | {"persist_to_workspace", "attach_workspace", "add_ssh_keys"}
)
# The keys of a workflow's job entry that are not the job's parameters.
_ENTRY_KEYS = frozenset(
    {"name", "requires", "context", "filters", "matrix", "type", "pre-steps", "post-steps", "serial-group"}
)
_PARAMETER = re.compile(r"<<\s*(pipeline\.)?parameters\.([\w-]+)\s*>>")


def _text(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _defaults(definition: Mapping[str, object]) -> dict[str, str]:
    declared = definition.get("parameters")
    if not isinstance(declared, Mapping):
        return {}
    return {
        str(name): _text(spec["default"])
        for name, spec in declared.items()
        if isinstance(spec, Mapping) and "default" in spec
    }


@dataclass(frozen=True, slots=True)
class _Scope:
    """What a definition's `<< ... >>` references name: its parameters and the pipeline's."""

    parameters: Mapping[str, str]
    pipeline: Mapping[str, str]

    def substituted(self, value: object) -> object:
        if isinstance(value, str):
            return _PARAMETER.sub(self._value, value)
        if isinstance(value, list):
            return [self.substituted(item) for item in value]
        if isinstance(value, Mapping):
            return {key: self.substituted(item) for key, item in value.items()}
        return value

    def _value(self, match: re.Match[str]) -> str:
        values = self.pipeline if match[1] else self.parameters
        return values.get(match[2], match[0])


@dataclass(frozen=True, slots=True, kw_only=True)
class _Config:
    path: str
    jobs: Mapping[str, object]
    commands: Mapping[str, object]
    executors: Mapping[str, object]
    orbs: frozenset[str]
    pipeline: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class _Runner:
    os: str
    image: str | None = None
    services: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None


def _images(docker: object) -> list[str]:
    entries = docker if isinstance(docker, list) else []
    return [str(entry["image"]) for entry in entries if isinstance(entry, Mapping) and "image" in entry]


def _executor(job: Mapping[str, object], config: _Config) -> Mapping[str, object] | None:
    """The executor's keys a job runs on: its own, or those of the named executor it uses; None for an orb's."""
    if not any(key in job for key in ("docker", "machine", "macos")) and "executor" in job:
        named = job["executor"]
        name = named.get("name") if isinstance(named, Mapping) else named
        found = config.executors.get(str(name))
        if not isinstance(found, Mapping):
            return None
        given = (
            {str(key): _text(value) for key, value in named.items() if key != "name"}
            if isinstance(named, Mapping)
            else {}
        )
        resolved = _Scope({**_defaults(found), **given}, config.pipeline).substituted(found)
        return resolved if isinstance(resolved, Mapping) else None
    return job


def _runner(job: Mapping[str, object], config: _Config) -> _Runner:
    executor = _executor(job, config)
    if executor is None:
        return _Runner(os="unknown")
    env = strings(executor.get("environment"))
    if (images := _images(executor.get("docker"))) and "docker" in executor:
        return _Runner(os="linux", image=images[0], services=tuple(images[1:]), env=env)
    if "macos" in executor:
        return _Runner(os="macos", env=env)
    machine = executor.get("machine")
    if machine:
        named = f"{machine.get('image', '') if isinstance(machine, Mapping) else ''} {job.get('resource_class', '')}"
        return _Runner(os="windows" if "windows" in detect_operating_systems(named) else "linux", env=env)
    return _Runner(os="unknown", env=env)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Job:
    """One run of a job, whose steps' facts go under `identity`, and whether it runs on Windows."""

    identity: str
    windows: bool


def _orb(name: str, config: _Config) -> str | None:
    owner = name.partition("/")[0]
    return owner if "/" in name and owner in config.orbs else None


def _unknown_step(config: _Config, at: _Path, name: str) -> Unknown:
    orb = _orb(name, config)
    reason = f"it is a command of the orb {orb}, which is not read" if orb else "it is not defined"
    return Unknown(origin=Origin(path=config.path, at=at), subject=f"the step {name}", reason=reason, hides="commands")


def _dialect(shell: object, *, windows: bool) -> tuple[Dialect, Shell | None]:
    """How a run step's lines are read and the shell options they run with."""
    if isinstance(shell, str):
        program = shell.split()[0].lower() if shell.split() else ""
        if "powershell" in program or "pwsh" in program:
            return POWERSHELL, None
        if program.endswith(("cmd", "cmd.exe")):
            return CMD, None
        return POSIX, shell_of(shell)
    return (POWERSHELL, None) if windows else (POSIX, STRICT)


def _run_facts(config: _Config, job: _Job, at: _Path, run: object, env: Mapping[str, str]) -> Iterator[Fact]:
    step = run if isinstance(run, Mapping) else {"command": run}
    command = step.get("command")
    if not isinstance(command, str):
        return
    dialect, shell = _dialect(step.get("shell"), windows=job.windows)
    facts = script_facts(
        command,
        job=job.identity,
        origin=Origin(path=config.path, at=(*at, "run", "command") if isinstance(run, Mapping) else (*at, "run")),
        env={**env, **strings(step.get("environment"))},
        directory=str(step["working_directory"]) if isinstance(step.get("working_directory"), str) else None,
        dialect=dialect,
        shell=shell,
    )
    yield from advised(facts, "runs in the background" if step.get("background") is True else "")


def _command_facts(
    config: _Config, job: _Job, at: _Path, name: str, given: object, env: Mapping[str, str], stack: tuple[str, ...]
) -> Iterator[Fact]:
    """The steps of the config's command `name`, with its parameters (the defaults under those `given`)."""
    if name in stack:
        yield Unknown(origin=Origin(path=config.path, at=at), subject=f"the command {name}", reason="it runs itself")
        return
    definition = config.commands[name]
    if not isinstance(definition, Mapping):
        return
    parameters = {**_defaults(definition), **{str(key): _text(value) for key, value in strings(given).items()}}
    steps = _Scope(parameters, config.pipeline).substituted(definition.get("steps"))
    yield from _steps_facts(config, job, ("commands", name, "steps"), steps, env, (*stack, name))


def _step_facts(
    config: _Config, job: _Job, at: _Path, step: object, env: Mapping[str, str], stack: tuple[str, ...]
) -> Iterator[Fact]:
    if isinstance(step, str):
        name, value = step, None
    elif isinstance(step, Mapping) and len(step) == 1:
        name, value = str(next(iter(step))), next(iter(step.values()))
    else:
        return
    if name in ("run", "deploy"):
        yield from _run_facts(config, job, at, value, env)
    elif name in ("when", "unless") and isinstance(value, Mapping):
        yield from _steps_facts(config, job, (*at, name, "steps"), value.get("steps"), env, stack)
    elif name in config.commands:
        yield from _command_facts(config, job, at, name, value, env, stack)
    elif name not in _BUILT_IN_STEPS:
        yield _unknown_step(config, at, name)


def _steps_facts(
    config: _Config, job: _Job, at: _Path, steps: object, env: Mapping[str, str], stack: tuple[str, ...] = ()
) -> Iterator[Fact]:
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        yield from _step_facts(config, job, (*at, index), step, env, stack)


def _job_facts(
    config: _Config, name: str, entry: Mapping[str, object], identity: str, shown: str, matrix: Mapping[str, str]
) -> Iterator[Fact]:
    """The facts of a run of job `name`: the parameters are its defaults under the workflow entry's own."""
    definition = config.jobs[name]
    if not isinstance(definition, Mapping):
        return
    own = {str(key): _text(value) for key, value in entry.items() if key not in _ENTRY_KEYS}
    resolved = _Scope({**_defaults(definition), **own, **matrix}, config.pipeline).substituted(definition)
    if not isinstance(resolved, Mapping):
        return
    runner = _runner(resolved, config)
    env = {**(runner.env or {}), **strings(resolved.get("environment"))}
    yield CiJob(
        origin=Origin(path=config.path, at=("jobs", name)),
        id=identity,
        provider=CIRCLECI.name,
        name=shown,
        os=runner.os,
        matrix=matrix,
        image=runner.image,
        services=runner.services,
        env=env,
    )
    job = _Job(identity=identity, windows=runner.os == "windows")
    steps = [*_list(entry.get("pre-steps")), *_list(resolved.get("steps")), *_list(entry.get("post-steps"))]
    yield from _steps_facts(config, job, ("jobs", name, "steps"), steps, env)


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _combinations(entry: Mapping[str, object]) -> list[dict[str, str]]:
    """The parameter values of each run of a workflow entry's `matrix`, without those it `exclude`s."""
    matrix = entry.get("matrix")
    parameters = matrix.get("parameters") if isinstance(matrix, Mapping) else None
    if not isinstance(parameters, Mapping):
        return [{}]
    names = [str(name) for name in parameters]
    values = [[_text(value) for value in _list(parameters[name]) or [parameters[name]]] for name in parameters]
    excluded = [strings(found) for found in _list(matrix.get("exclude"))] if isinstance(matrix, Mapping) else []
    found = (dict(zip(names, combination, strict=True)) for combination in itertools.product(*values))
    return [combination for combination in found if combination not in excluded]


def _entries(document: Mapping[str, object]) -> Iterator[tuple[str, str, Mapping[str, object], _Path]]:
    """Each job entry of each workflow: the workflow, the job it runs, its configuration, where it is written."""
    workflows = document.get("workflows")
    for workflow, definition in workflows.items() if isinstance(workflows, Mapping) else ():
        jobs = definition.get("jobs") if isinstance(definition, Mapping) else None
        for index, entry in enumerate(_list(jobs)):
            at: _Path = ("workflows", str(workflow), "jobs", index)
            if isinstance(entry, str):
                yield str(workflow), entry, {}, at
            elif isinstance(entry, Mapping) and len(entry) == 1:
                name, configuration = next(iter(entry.items()))
                yield str(workflow), str(name), configuration if isinstance(configuration, Mapping) else {}, at


def _workflow_facts(config: _Config, document: Mapping[str, object]) -> Iterator[Fact]:
    for workflow, name, entry, at in _entries(document):
        if name not in config.jobs:
            orb = _orb(name, config)
            reason = f"it is a job of the orb {orb}, which is not read" if orb else "it is not defined"
            yield Unknown(
                origin=Origin(path=config.path, at=at), subject=f"the job {name}", reason=reason, hides="jobs"
            )
            continue
        for combination in _combinations(entry):
            shown = str(entry.get("name") or "-".join((name, *combination.values())))
            identity = f"{config.path}:{workflow}:{shown}"
            yield from _job_facts(config, name, entry, identity, shown, combination)


def _mapping(value: object) -> Mapping[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def circleci_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """The jobs the config's workflows run (each job once, without workflows), with the commands of their steps."""
    if not isinstance(document, Mapping):
        return
    config = _Config(
        path=path,
        jobs=_mapping(document.get("jobs")),
        commands=_mapping(document.get("commands")),
        executors=_mapping(document.get("executors")),
        orbs=frozenset(_mapping(document.get("orbs"))),
        pipeline=_defaults(document),
    )
    if isinstance(document.get("workflows"), Mapping):
        yield from _workflow_facts(config, document)
        return
    for name in config.jobs:
        yield from _job_facts(config, name, {}, f"{path}:{name}", name, {})


CIRCLECI = CiProvider(
    name="CircleCI",
    files=(".circleci/config.yml",),
    linters=(pattern("circleci config validate", r"\bcircleci\s+config\s+validate\b"),),
    lint_hint="CircleCI: run circleci config validate in CI",
    badges=(
        pattern(
            "CircleCI", r"circleci\.com/(?:gh|bb)/\S+\.svg|dl\.circleci\.com/status-badge/|img\.shields\.io/circleci/"
        ),
    ),
    facts=circleci_facts,
)
