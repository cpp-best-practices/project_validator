"""Travis CI: `.travis.yml` read as its jobs and the commands of their phases (upstream #223).

The build matrix is every combination of the root's expansion keys (`os`, `arch`, `compiler`, `env` and the language
version keys: `python`, `node_js`, `go`, ...), without the `jobs.exclude` entries; each `jobs.include` entry adds a
job of its own, with the root's keys under its own and the first value of each expansion key it does not set
(`matrix:` is the old name of `jobs:`). A job that `jobs.allow_failures` matches cannot fail the build. Each line of
a phase runs as a script of its own; the build fails on a failing line of `before_install`, `install`,
`before_script` and `script`, never on one of `after_success`, `after_failure` or `after_script`. A Windows job runs
its lines in Git Bash. A job with no `script` runs its language's default script, which is not read.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load
from project_validator.facts import CiJob, Fact, Origin, Unknown
from project_validator.facts.exit_status import POSIX as POSIX_SHELL
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import ShellSyntaxError, split_words
from project_validator.platforms import detect_operating_systems
from project_validator.templates import SHELL, known
from project_validator.text import pattern

# The keys whose list of values each make a job of the build matrix.
_LANGUAGE_VERSIONS = (
    *("python", "node_js", "go", "rvm", "ruby", "jdk", "php", "perl", "scala", "rust", "dart", "julia"),
    *("elixir", "otp_release", "ghc", "crystal", "d", "dotnet", "mono", "r", "haxe", "smalltalk", "nix"),
)
_EXPANSION = ("os", "arch", "compiler", "env", *_LANGUAGE_VERSIONS)
# A version key as the profiles read a version: under the name of the setup action's input (`python: 3.12` is
# setup-python's `python-version: 3.12`).
_VERSION_NAMES = {
    **{key: f"{key}-version" for key in ("python", "go", "php", "perl", "scala", "julia", "elixir", "ghc", "dotnet")},
    "node_js": "node-version",
    "rvm": "ruby-version",
    "ruby": "ruby-version",
    "jdk": "java-version",
    "otp_release": "otp-version",
    "r": "r-version",
    "rust": "toolchain",
}
# A JDK as Travis names it (`openjdk11`, `oraclejdk8`): its version is the number.
_JDK_VENDOR = re.compile(r"^[a-z]+jdk(?=\d)")
_FAILING_PHASES = ("before_install", "install", "before_script", "script")
_IGNORED_PHASES = ("after_success", "after_failure", "after_script")
# Languages whose default script is nothing a check could read.
_NO_DEFAULT_SCRIPT = frozenset({"generic", "minimal", "shell", "bash", "sh"})

type _Job = dict[str, object]


def _values(value: object) -> list[object]:
    return value if isinstance(value, list) else [] if value is None else [value]


def _env_values(value: object) -> tuple[list[object], list[object]]:
    """The global environment lines and the matrix ones of an `env:` key: a list is the matrix; a mapping holds
    `global:` and `jobs:` (or `matrix:`)."""
    if isinstance(value, Mapping):
        return _values(value.get("global")), _values(value.get("jobs", value.get("matrix")))
    return [], _values(value)


def _assignments(line: object) -> dict[str, str]:
    """The variables of an env line (`A=1 B="x y"`); an encrypted one (`secure:`) sets none that can be read."""
    if not isinstance(line, str):
        return {}
    try:
        words = split_words(line)
    except ShellSyntaxError:
        return {}
    return {name: value for name, sign, value in (word.partition("=") for word in words) if sign}


def _first(value: object) -> object:
    values = _values(value)
    return values[0] if values else None


def _root_jobs(root: Mapping[str, object], includes: bool) -> list[_Job]:
    """The jobs of the root's expansion keys: one per combination of the values of those it sets; one with none set,
    unless the build is only its `jobs.include` entries."""
    _, env = _env_values(root.get("env"))
    keys = [key for key in _EXPANSION if (env if key == "env" else _values(root.get(key)))]
    if not keys and includes:
        return []
    choices = [env if key == "env" else _values(root[key]) for key in keys]
    return [{**root, **dict(zip(keys, combination, strict=True))} for combination in itertools.product(*choices)]


def _matches(job: Mapping[str, object], entry: object) -> bool:
    """Whether a `jobs.exclude` or `jobs.allow_failures` entry names `job`: every key it sets has the job's value."""
    return isinstance(entry, Mapping) and all(job.get(key) == value for key, value in entry.items())


def _included(root: Mapping[str, object], entry: Mapping[str, object]) -> _Job:
    firsts = {key: _first(root.get(key)) for key in _EXPANSION if key != "env" and _values(root.get(key))}
    _, env = _env_values(root.get("env"))
    if env:
        firsts["env"] = env[0]
    return {**root, **firsts, **entry}


def _jobs(root: Mapping[str, object]) -> Iterator[tuple[_Job, tuple[str | int, ...], frozenset[str]]]:
    """Each job with where it is written and the keys written there: the root's, then each `jobs.include`
    entry's."""
    section = root.get("jobs", root.get("matrix"))
    section = section if isinstance(section, Mapping) else {}
    key = "jobs" if "jobs" in root else "matrix"
    includes = [entry for entry in _values(section.get("include")) if isinstance(entry, Mapping)]
    excluded = _values(section.get("exclude"))
    own = {name: value for name, value in root.items() if name not in ("jobs", "matrix")}
    for job in _root_jobs(own, bool(includes)):
        if not any(_matches(job, entry) for entry in excluded):
            yield job, (), frozenset()
    for index, entry in enumerate(_values(section.get("include"))):
        if isinstance(entry, Mapping):
            yield _included(own, entry), (key, "include", index), frozenset(map(str, entry))


def _os(job: Mapping[str, object]) -> str:
    found = detect_operating_systems(str(job.get("os") or "linux"))
    return found[0] if found else "unknown"


def _matrix(job: Mapping[str, object]) -> dict[str, str]:
    """The job's values of the expansion keys, as its matrix (the toolchains and compilers it names), each version
    under the name the profiles read it by."""
    return {
        _VERSION_NAMES.get(key, key): _JDK_VENDOR.sub("", str(job[key])) if key == "jdk" else str(job[key])
        for key in _EXPANSION
        if key not in ("os", "env") and job.get(key) is not None
    }


def _name(job: Mapping[str, object], matrix: Mapping[str, str]) -> str:
    """The name the job is given, else what tells it apart: its OS where it sets one, its matrix values and env."""
    if isinstance(job.get("name"), str):
        return str(job["name"])
    shown = [
        *([str(job["os"])] if isinstance(job.get("os"), str) else []),
        *matrix.values(),
        *([str(job["env"])] if isinstance(job.get("env"), str) else []),
    ]
    return ", ".join(shown) or "linux"


def _lines(value: object) -> list[str]:
    return [line for line in _values(value) if isinstance(line, str)]


def _environment(root: Mapping[str, object], job: _Job) -> dict[str, str]:
    """The variables a job runs with: the global env lines, then its own line of the matrix."""
    global_env, _ = _env_values(root.get("env"))
    own = job.get("env")
    lines = (*global_env, *([own] if not isinstance(own, (list, Mapping)) else []))
    return {name: value for line in lines for name, value in _assignments(line).items()}


def _allowed_to_fail(root: Mapping[str, object], job: _Job) -> str:
    section = root.get("jobs", root.get("matrix"))
    allowed = section.get("allow_failures") if isinstance(section, Mapping) else None
    return "allowed to fail (jobs.allow_failures)" if any(_matches(job, entry) for entry in _values(allowed)) else ""


def _phase_facts(
    path: str, job: _Job, at: tuple[str | int, ...], own: frozenset[str], identity: str, env: Mapping[str, str]
) -> Iterator[Fact]:
    """The commands of each line of the job's phases, those of the phases after the script cannot fail it."""
    for phase in (*_FAILING_PHASES, *_IGNORED_PHASES):
        written = (*at, phase) if phase in own else (phase,)
        ignored = f"in {phase}, whose failure Travis CI ignores" if phase in _IGNORED_PHASES else ""
        for number, line in enumerate(_lines(job.get(phase))):
            origin = Origin(path=path, at=(*written, number))
            text = SHELL.substituted(line, known(env))
            yield from advised(script_facts(text, job=identity, origin=origin, env=env, shell=POSIX_SHELL), ignored)


def _job_facts(
    path: str, root: Mapping[str, object], job: _Job, at: tuple[str | int, ...], own: frozenset[str], identity: str
) -> Iterator[Fact]:
    env, matrix = _environment(root, job), _matrix(job)
    name = _name(job, matrix)
    yield CiJob(
        origin=Origin(path=path, at=at),
        id=identity,
        provider=TRAVIS_CI.name,
        name=name,
        os=_os(job),
        matrix=matrix,
        services=tuple(str(service) for service in _values(job.get("services"))),
        env=env,
    )
    language = str(job.get("language") or "")
    if "script" not in job and language and language not in _NO_DEFAULT_SCRIPT:
        reason = f"it runs the default script of language {language}, which is not read"
        yield Unknown(origin=Origin(path=path, at=at), subject=f"the commands of job {name}", reason=reason)
    yield from advised(_phase_facts(path, job, at, own, identity, env), _allowed_to_fail(root, job))


def travis_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """The jobs of `.travis.yml`, one per combination of its build matrix and one per included job, with the
    commands each one runs."""
    if not isinstance(document, Mapping):
        return
    root = {str(key): value for key, value in document.items()}
    jobs = list(_jobs(root))
    for index, (job, at, own) in enumerate(jobs):
        identity = path if len(jobs) == 1 else f"{path}[{index}]"
        yield from _job_facts(path, root, job, at, own, identity)


TRAVIS_CI = CiProvider(
    name="Travis CI",
    files=(".travis.yml",),
    badges=(pattern("Travis CI", r"travis-ci\.com/\S+\.svg|img\.shields\.io/travis/"),),
    retired_badges=(pattern("travis-ci.org, which shut down in June 2021", r"(?<![\w.-])(?:api\.)?travis-ci\.org/"),),
    facts=travis_facts,
)
