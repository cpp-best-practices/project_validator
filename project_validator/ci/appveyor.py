"""AppVeyor: `appveyor.yml` read as its build matrix and the commands of each job's phases (upstream #223).

The matrix is every combination of `image`, `platform`, `configuration` and the `environment: matrix:` entries,
without those `matrix: exclude:` names; a job `matrix: allow_failures:` names cannot fail the build. A `for:` entry
whose `matrix: only:` (or `except:`) conditions name a job gives it the keys it sets. A job runs with the global
environment, its matrix entry's and the `CONFIGURATION` and `PLATFORM` AppVeyor sets; `%NAME%` and `$NAME` are
replaced by their values. The OS is the image's (an entry's `APPVEYOR_BUILD_WORKER_IMAGE` over the job's; Visual
Studio 2015, on Windows, without one). Each script line runs on its own, in cmd on Windows and in bash elsewhere, or
in the shell its entry names (`cmd:`, `ps:`, `pwsh:`, `sh:`); the lines of `on_success`, `on_failure` and `on_finish`
cannot fail the build. On Windows, a job without a `build_script` builds with MSBuild: the `build: project:` it
names, or else the solution it finds, which is not read.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin, Unknown
from project_validator.facts.exit_status import POSIX as POSIX_SHELL
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import CMD, POSIX, POWERSHELL, Dialect
from project_validator.platforms import detect_operating_systems
from project_validator.templates import SHELL, known
from project_validator.text import pattern

type _Job = dict[str, object]

_PHASES = ("init", "install", "before_build", "build_script", "after_build", "before_test", "test_script", "after_test")
_IGNORED_PHASES = ("on_success", "on_failure", "on_finish")
_EXPANSION = ("image", "platform", "configuration")
_DEFAULT_IMAGE = "Visual Studio 2015"
_CMD_VARIABLE = re.compile(r"%(\w+)%")
_SHELLS: dict[str, Dialect] = {"cmd": CMD, "ps": POWERSHELL, "pwsh": POWERSHELL, "sh": POSIX}


def _values(value: object) -> list[object]:
    return value if isinstance(value, list) else [] if value is None else [value]


def _environment(root: Mapping[str, object]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """The global variables (`global:`, and those beside `matrix:`) and the matrix entries of `environment:`."""
    environment = root.get("environment")
    if not isinstance(environment, Mapping):
        return {}, [{}]
    plain = strings({key: value for key, value in environment.items() if key not in ("global", "matrix")})
    entries = [strings(entry) for entry in _values(environment.get("matrix")) if isinstance(entry, Mapping)]
    return {**strings(environment.get("global")), **plain}, entries or [{}]


def _matches(job: Mapping[str, object], env: Mapping[str, str], condition: object) -> bool:
    """Whether a matrix condition (`image: Ubuntu`, `configuration: Debug`, a variable's value) names the job."""
    if not isinstance(condition, Mapping):
        return False
    return all(str(job.get(key, env.get(str(key)))) == str(value) for key, value in condition.items())


def _sections(root: Mapping[str, object], job: _Job, env: Mapping[str, str]) -> _Job:
    """The job with the keys of each `for:` entry that names it."""
    merged = dict(job)
    for entry in _values(root.get("for")):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("matrix"), Mapping):
            continue
        only, excepted = _values(entry["matrix"].get("only")), _values(entry["matrix"].get("except"))
        named = any(_matches(job, env, condition) for condition in only) if only else True
        if named and not any(_matches(job, env, condition) for condition in excepted):
            merged.update({str(key): value for key, value in entry.items() if key != "matrix"})
    return merged


def _jobs(root: Mapping[str, object]) -> Iterator[tuple[_Job, dict[str, str], dict[str, str], str]]:
    """Each job of the matrix, its variables, its environment matrix entry and why it cannot fail the build ("" when
    it can)."""
    global_env, entries = _environment(root)
    found = root.get("matrix")
    matrix: Mapping[str, object] = found if isinstance(found, Mapping) else {}
    keys = [key for key in _EXPANSION if _values(root.get(key))]
    choices = [_values(root[key]) for key in keys]
    for combination, entry in itertools.product(itertools.product(*choices), entries):
        job: _Job = {**root, **dict(zip(keys, combination, strict=True))}
        env = {**global_env, **entry}
        env |= {name.upper(): str(job[name]) for name in ("platform", "configuration") if job.get(name) is not None}
        if any(_matches(job, env, condition) for condition in _values(matrix.get("exclude"))):
            continue
        allowed = any(_matches(job, env, condition) for condition in _values(matrix.get("allow_failures")))
        yield _sections(root, job, env), env, entry, "allowed to fail (matrix.allow_failures)" if allowed else ""


def _image(job: Mapping[str, object], env: Mapping[str, str]) -> str:
    return env.get("APPVEYOR_BUILD_WORKER_IMAGE") or str(job.get("image") or _DEFAULT_IMAGE)


# AppVeyor's image names: `Ubuntu2204`, `macos-sonoma`, `Visual Studio 2022`.
_IMAGE_SYSTEMS = (("ubuntu", "linux"), ("macos", "macos"), ("visual studio", "windows"))


def _os(image: str) -> str:
    named = image.strip().lower()
    found = [system for prefix, system in _IMAGE_SYSTEMS if named.startswith(prefix)] or detect_operating_systems(image)
    return found[0] if found else "unknown"


def _line(entry: object, windows: bool) -> tuple[str, Dialect] | None:
    if isinstance(entry, str):
        return entry, CMD if windows else POSIX
    if isinstance(entry, Mapping):
        for key, dialect in _SHELLS.items():
            if isinstance(entry.get(key), str):
                return str(entry[key]), dialect
    return None


def _substituted(text: str, env: Mapping[str, str]) -> str:
    return SHELL.substituted(_CMD_VARIABLE.sub(lambda match: env.get(match[1], match[0]), text), known(env))


def _phase_facts(path: str, job: _Job, env: Mapping[str, str], identity: str, windows: bool) -> Iterator[Fact]:
    for phase in (*_PHASES, *_IGNORED_PHASES):
        ignored = f"in {phase}, whose failure AppVeyor ignores" if phase in _IGNORED_PHASES else ""
        for number, entry in enumerate(_values(job.get(phase))):
            if (found := _line(entry, windows)) is None:
                continue
            text, dialect = found
            facts = script_facts(
                _substituted(text, env),
                job=identity,
                origin=Origin(path=path, at=(phase, number)),
                env=env,
                dialect=dialect,
                shell=POSIX_SHELL if dialect is POSIX else None,
            )
            yield from advised(facts, ignored)


def _build_facts(path: str, job: _Job, identity: str, name: str) -> Iterator[Fact]:
    """AppVeyor's own MSBuild build, on Windows, of a job without a build script."""
    build = job.get("build")
    if "build_script" in job or build in ("off", False):
        return
    origin = Origin(path=path, at=("build",))
    project = build.get("project") if isinstance(build, Mapping) else None
    if not isinstance(project, str):
        reason = "AppVeyor builds the solution it finds with MSBuild, which is not read"
        yield Unknown(origin=origin, subject=f"the build of job {name}", reason=reason, hides="commands")
        return
    configuration = (f"/p:Configuration={job['configuration']}",) if job.get("configuration") else ()
    yield from script_facts(" ".join(("msbuild", project, *configuration)), job=identity, origin=origin)


def appveyor_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """The jobs of the build matrix, with the commands each one runs."""
    if not isinstance(document, Mapping):
        return
    root = {str(key): value for key, value in document.items()}
    jobs = list(_jobs(root))
    for index, (job, env, entry, advisory) in enumerate(jobs):
        identity = path if len(jobs) == 1 else f"{path}[{index}]"
        image = _image(job, env)
        os = _os(image)
        shown = [str(job[key]) for key in _EXPANSION if job.get(key) is not None and _values(root.get(key))]
        name = ", ".join([*shown, *entry.values()][:4]) or image
        # The image names the OS, not a compiler: Visual Studio 2015 also has MinGW.
        matrix = {**{key: str(job[key]) for key in ("platform", "configuration") if job.get(key) is not None}, **entry}
        yield CiJob(
            origin=Origin(path=path), id=identity, provider=APPVEYOR.name, name=name, os=os, matrix=matrix, env=env
        )
        facts = _phase_facts(path, job, env, identity, os == "windows")
        if os == "windows":
            facts = itertools.chain(facts, _build_facts(path, job, identity, name))
        yield from advised(facts, advisory)


APPVEYOR = CiProvider(
    name="AppVeyor",
    files=("appveyor.yml", ".appveyor.yml"),
    badges=(pattern("AppVeyor", r"ci\.appveyor\.com/api/projects/status|img\.shields\.io/appveyor/"),),
    configured_elsewhere=True,
    facts=appveyor_facts,
)
