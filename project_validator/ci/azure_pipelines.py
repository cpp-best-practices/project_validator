"""Azure Pipelines: a pipeline read as its jobs and the commands of their steps (upstream #223).

A pipeline is its `stages:`, each of `jobs:`, or its `jobs:`, or one job of its `steps:`; each leg of a job's
`strategy: matrix:` is a job of its own. A job runs on its pool (its stage's, the pipeline's): the OS its `vmImage`
names, Microsoft's Ubuntu image when there is no pool, and an unknown OS for a pool of the organisation's own
agents. `$(name)` and `${{ variables.name }}` are replaced by the values the pipeline's, the stage's, the job's and
the leg's variables give. A `script:` step runs in bash (in cmd on Windows); `bash:`, `pwsh:` and `powershell:` name
their shell; the known tasks run their commands (`CmdLine`, `Bash`, `PowerShell`, `DotNetCoreCLI`, `Maven`,
`Gradle`, `CMake`, `Npm`, `MSBuild`, `VSBuild`) or set up their toolchain (`UseDotNet`, `UsePythonVersion`, `NodeTool`,
`JavaToolInstaller`, `GoTool`); other tasks run nothing of the project's. A step that continues on error cannot fail
the job. Templates are not read, nor is a matrix an expression computes: both are unknown. Deployment jobs, which
deploy rather than build, are not jobs of the project's.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin, Unknown
from project_validator.facts.exit_status import POSIX as POSIX_SHELL
from project_validator.facts.exit_status import Shell
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import CMD, POSIX, POWERSHELL, Dialect, ShellSyntaxError, command_line, split_words
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern

type _Path = tuple[str | int, ...]

_MACRO = re.compile(r"\$\((\w[\w.]*)\)|\$\{\{\s*variables\.(\w[\w.]*)\s*\}\}")
# A task's toolchain input, as the profiles read a version: under the name of the GitHub setup action's input.
_TOOLCHAIN_TASKS = {
    "usedotnet": ("version", "dotnet-version"),
    "usepythonversion": ("versionSpec", "python-version"),
    "nodetool": ("versionSpec", "node-version"),
    "javatoolinstaller": ("versionSpec", "java-version"),
    "gotool": ("version", "go-version"),
}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _variables(value: object) -> dict[str, str]:
    """Variables as a mapping, or as a list of `name:`/`value:` entries (a `group:` or `template:` names none that
    can be read)."""
    if isinstance(value, Mapping):
        return strings(value)
    entries = (entry for entry in _list(value) if isinstance(entry, Mapping) and "name" in entry)
    return {str(entry["name"]): str(entry.get("value", "")) for entry in entries}


@dataclass(frozen=True, slots=True, kw_only=True)
class _Job:
    """One leg of a job: where its facts go, its variables, and the OS its steps run on."""

    path: str
    identity: str
    variables: Mapping[str, str]
    windows: bool

    def substituted(self, text: str) -> str:
        return _MACRO.sub(lambda match: self.variables.get(match[1] or match[2], match[0]), text)


def _os(pool: object, variables: Mapping[str, str]) -> str:
    if pool is None:
        return "linux"
    image = pool.get("vmImage") if isinstance(pool, Mapping) else None
    if image is None:
        return "unknown"
    named = _MACRO.sub(lambda match: variables.get(match[1] or match[2], ""), str(image))
    found = detect_operating_systems(named)
    return found[0] if found else "unknown"


def _image(container: object) -> str | None:
    image = container.get("image") if isinstance(container, Mapping) else container
    return str(image) if isinstance(image, str) else None


def _words(text: object) -> tuple[str, ...]:
    try:
        return split_words(str(text)) if isinstance(text, str) else ()
    except ShellSyntaxError:
        return ()


def _dotnet(inputs: Mapping[str, str]) -> tuple[str, ...]:
    command = inputs.get("command", "build")
    verb = inputs.get("custom", "") if command == "custom" else command
    return ("dotnet", *_words(verb), *_words(inputs.get("projects")), *_words(inputs.get("arguments")))


def _msbuild(inputs: Mapping[str, str]) -> tuple[str, ...]:
    configuration = (f"/p:Configuration={inputs['configuration']}",) if inputs.get("configuration") else ()
    return ("msbuild", *_words(inputs.get("solution")), *configuration, *_words(inputs.get("msbuildArgs")))


# A task (by its name, without the version) and the command line it runs from its inputs.
_COMMAND_TASKS = {
    "dotnetcorecli": _dotnet,
    "maven": lambda inputs: ("mvn", *_words(inputs.get("options")), *_words(inputs.get("goals", "package"))),
    "gradle": lambda inputs: (inputs.get("gradleWrapperFile", "gradlew"), *_words(inputs.get("tasks", "build"))),
    "cmake": lambda inputs: ("cmake", *_words(inputs.get("cmakeArgs"))),
    "npm": lambda inputs: (
        ("npm", *_words(inputs.get("customCommand")))
        if inputs.get("command") == "custom"
        else ("npm", inputs.get("command", "install"))
    ),
    "msbuild": _msbuild,
    "vsbuild": _msbuild,
}
# A task that runs a script from its inputs: how it is read on Windows, and elsewhere.
_SCRIPT_TASKS: dict[str, tuple[Dialect, Dialect]] = {
    "cmdline": (CMD, POSIX),
    "bash": (POSIX, POSIX),
    "powershell": (POWERSHELL, POWERSHELL),
}


def _script(step: Mapping[str, object], windows: bool) -> tuple[str, str, Dialect] | None:
    """A step's script: its key, its text and how it is read."""
    for key, dialect in (
        ("script", CMD if windows else POSIX),
        ("bash", POSIX),
        ("pwsh", POWERSHELL),
        ("powershell", POWERSHELL),
    ):
        if isinstance(step.get(key), str):
            return key, str(step[key]), dialect
    return None


def _script_facts(job: _Job, step: Mapping[str, object], origin: Origin, text: str, dialect: Dialect) -> Iterator[Fact]:
    shell: Shell | None = POSIX_SHELL if dialect is POSIX else None
    directory = step.get("workingDirectory")
    facts = script_facts(
        job.substituted(text),
        job=job.identity,
        origin=origin,
        env={**job.variables, **strings(step.get("env"))},
        directory=job.substituted(directory) if isinstance(directory, str) else None,
        condition=str(step["condition"]) if isinstance(step.get("condition"), str) else None,
        dialect=dialect,
        shell=shell,
    )
    yield from advised(facts, "continueOnError" if step.get("continueOnError") is True else "")


def _task_facts(job: _Job, step: Mapping[str, object], at: _Path) -> Iterator[Fact]:
    name = str(step["task"]).partition("@")[0].lower()
    inputs = {key: job.substituted(value) for key, value in strings(step.get("inputs")).items()}
    origin = Origin(path=job.path, at=(*at, "task"))
    if name in _SCRIPT_TASKS:
        windows_dialect, dialect = _SCRIPT_TASKS[name]
        if inputs.get("targetType", "inline") == "inline" and "script" in inputs:
            yield from _script_facts(job, step, origin, inputs["script"], windows_dialect if job.windows else dialect)
        elif "filePath" in inputs:
            program = "pwsh" if name == "powershell" else "bash"
            line = " ".join((program, inputs["filePath"], inputs.get("arguments", "")))
            yield from _script_facts(job, step, origin, line, POSIX)
    elif name in _COMMAND_TASKS:
        line = command_line(_COMMAND_TASKS[name](inputs))
        yield from _script_facts(job, step, origin, line, POSIX)


def _steps_facts(job: _Job, steps: object, at: _Path) -> Iterator[Fact]:
    for index, step in enumerate(_list(steps)):
        if not isinstance(step, Mapping):
            continue
        place = (*at, index)
        if isinstance(step.get("template"), str):
            subject = f"the template {step['template']}"
            origin = Origin(path=job.path, at=place)
            yield Unknown(origin=origin, subject=subject, reason="templates are not read", hides="commands")
        elif isinstance(step.get("task"), str):
            yield from _task_facts(job, step, place)
        elif (script := _script(step, job.windows)) is not None:
            key, text, dialect = script
            yield from _script_facts(job, step, Origin(path=job.path, at=(*place, key)), text, dialect)


def _toolchains(steps: object, variables: Mapping[str, str]) -> dict[str, str]:
    """The toolchain versions the job's tasks set up, named as the profiles read them, each under its step (a job
    may install two .NET SDKs)."""
    found: dict[str, str] = {}
    for index, step in enumerate(_list(steps)):
        if isinstance(step, Mapping) and isinstance(step.get("task"), str):
            name = str(step["task"]).partition("@")[0].lower()
            if name in _TOOLCHAIN_TASKS and isinstance(inputs := step.get("inputs"), Mapping):
                key, named = _TOOLCHAIN_TASKS[name]
                if key in inputs:
                    found[f"steps[{index}] {named}"] = _MACRO.sub(
                        lambda match: variables.get(match[1] or match[2], match[0]), str(inputs[key])
                    )
    return found


@dataclass(frozen=True, slots=True, kw_only=True)
class _Context:
    """Where a job is: the pipeline's file, the variables and pool of the levels above it."""

    path: str
    variables: Mapping[str, str]
    pool: object
    prefix: str


def _legs(job: Mapping[str, object]) -> dict[str, dict[str, str]] | None:
    """A job's matrix legs by name (one unnamed leg without a matrix); None for a matrix an expression computes."""
    strategy = job.get("strategy")
    matrix = strategy.get("matrix") if isinstance(strategy, Mapping) else None
    if matrix is None:
        return {"": {}}
    if not isinstance(matrix, Mapping):
        return None
    return {str(leg): strings(values) for leg, values in matrix.items()} or {"": {}}


def _job_facts(context: _Context, job: Mapping[str, object], at: _Path) -> Iterator[Fact]:
    name = str(job.get("job") or "job")
    shown = str(job.get("displayName") or name)
    legs = _legs(job)
    origin = Origin(path=context.path, at=at)
    if legs is None:
        reason = "it is computed by an expression"
        yield Unknown(origin=origin, subject=f"the matrix of job {shown}", reason=reason, hides="jobs")
        return
    for leg, values in legs.items():
        variables = {**context.variables, **_variables(job.get("variables")), **values}
        os = _os(job.get("pool", context.pool), variables)
        identity = f"{context.path}:{context.prefix}{name}" + (f"[{leg}]" if leg else "")
        yield CiJob(
            origin=origin,
            id=identity,
            provider=AZURE_PIPELINES.name,
            name=f"{shown} ({leg})" if leg else shown,
            os=os,
            matrix={**values, **_toolchains(job.get("steps"), variables)},
            image=_image(job.get("container")),
            services=tuple(image for found in strings(job.get("services")).values() if (image := _image(found))),
            env=variables,
        )
        state = _Job(path=context.path, identity=identity, variables=variables, windows=os == "windows")
        yield from _steps_facts(state, job.get("steps"), (*at, "steps"))


def _template(context: _Context, entry: Mapping[str, object], at: _Path, hides: str) -> Unknown:
    subject = f"the template {entry['template']}"
    return Unknown(
        origin=Origin(path=context.path, at=at), subject=subject, reason="templates are not read", hides=hides
    )


def _jobs_facts(context: _Context, jobs: object, at: _Path) -> Iterator[Fact]:
    for index, job in enumerate(_list(jobs)):
        if not isinstance(job, Mapping):
            continue
        if isinstance(job.get("template"), str):
            yield _template(context, job, (*at, index), "jobs")
        elif "job" in job or "steps" in job:
            yield from _job_facts(context, job, (*at, index))


def _stages_facts(context: _Context, stages: object) -> Iterator[Fact]:
    for index, stage in enumerate(_list(stages)):
        if not isinstance(stage, Mapping):
            continue
        if isinstance(stage.get("template"), str):
            yield _template(context, stage, ("stages", index), "jobs")
            continue
        within = replace(
            context,
            variables={**context.variables, **_variables(stage.get("variables"))},
            pool=stage.get("pool", context.pool),
            prefix=f"{stage.get('stage', index)}.",
        )
        yield from _jobs_facts(within, stage.get("jobs"), ("stages", index, "jobs"))


def pipeline_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """The jobs of a pipeline, one per matrix leg, with the commands each one runs."""
    if not isinstance(document, Mapping):
        return
    context = _Context(path=path, variables=_variables(document.get("variables")), pool=document.get("pool"), prefix="")
    if isinstance(document.get("extends"), Mapping) and "template" in document["extends"]:
        yield _template(context, document["extends"], ("extends",), "jobs")
    if "stages" in document:
        yield from _stages_facts(context, document["stages"])
    elif "jobs" in document:
        yield from _jobs_facts(context, document["jobs"], ("jobs",))
    elif "steps" in document:
        yield from _job_facts(context, {"job": "job", **document}, ())


AZURE_PIPELINES = CiProvider(
    name="Azure Pipelines",
    files=(
        *("azure-pipelines.yml", "azure-pipelines.yaml", ".azure-pipelines.yml"),
        # The ansible collections' standard location, and Azure DevOps' old default name (dotnet/command-line-api).
        *(".azure-pipelines/azure-pipelines.yml", ".vsts-ci.yml"),
    ),
    badges=(
        pattern(
            "Azure Pipelines",
            r"(?:dev\.azure\.com|\w+\.visualstudio\.com)/\S+/_apis/build/status|img\.shields\.io/azure-devops/build/",
        ),
    ),
    configured_elsewhere=True,
    facts=pipeline_facts,
)
