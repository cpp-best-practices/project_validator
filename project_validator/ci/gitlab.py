"""GitLab CI: jobs are parsed, `parallel: matrix:` is expanded and the runner OS comes from the job's tags."""

import itertools
import json
import re
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin, Unknown
from project_validator.facts.expansion import script_facts
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern

type Variables = dict[str, str]

_RESERVED_KEYS = frozenset(
    {"stages", "variables", "default", "include", "workflow"}
    | {"image", "services", "before_script", "after_script", "cache"}
)
_VARIABLE = re.compile(r"\$\{?(\w+)\}?")


def _entry_combinations(entry: Mapping[str, object]) -> list[Variables]:
    values = [value if isinstance(value, list) else [value] for value in entry.values()]
    return [dict(zip(entry, map(str, combination), strict=True)) for combination in itertools.product(*values)]


def expand_parallel(parallel: object) -> list[Variables]:
    if not isinstance(parallel, Mapping) or not isinstance(matrix := parallel.get("matrix"), list):
        return [{}]
    return [
        combination for entry in matrix if isinstance(entry, Mapping) for combination in _entry_combinations(entry)
    ] or [{}]


def substitute_variables(text: str, variables: Variables) -> str:
    return _VARIABLE.sub(lambda match: variables.get(match[1], match[0]), text)


def _runner_os(tags: str) -> str:
    found = [os for os in detect_operating_systems(tags) if os != "linux"]
    return found[0] if found else "linux"


def _is_job(name: str, job: object) -> bool:
    return (
        name not in _RESERVED_KEYS
        and not name.startswith(".")
        and isinstance(job, Mapping)
        and "trigger" not in job
        and ("script" in job or "extends" in job)
    )


_SCRIPTS = ("before_script", "script", "after_script")


def _script_lines(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [line for line in value if isinstance(line, str)] if isinstance(value, list) else []


def _job_facts(path: str, name: str, job: Mapping[str, object], defaults: Mapping[str, object]) -> Iterator[Fact]:
    origin = Origin(path=path, at=(name,))
    if "extends" in job:
        yield Unknown(origin=origin, subject=f"job {name}", reason="extends: is not resolved")
    image = job.get("image", defaults.get("image"))
    image_name = image.get("name") if isinstance(image, Mapping) else image
    tags = json.dumps(job.get("tags", defaults.get("tags", [])), default=str)
    combinations = expand_parallel(job.get("parallel"))
    for index, variables in enumerate(combinations):
        identity = f"{path}:{name}" if len(combinations) == 1 else f"{path}:{name}[{index}]"
        env = {**strings(defaults.get("variables")), **strings(job.get("variables")), **variables}
        os = _runner_os(substitute_variables(tags, variables))
        yield CiJob(
            origin=origin,
            id=identity,
            provider=GITLAB_CI.name,
            name=f"{name} ({', '.join(variables.values())})" if variables else name,
            os=os,
            matrix=variables,
            image=substitute_variables(image_name, variables)
            if isinstance(image_name, str) and os == "linux"
            else None,
            env=env,
        )
        for key in _SCRIPTS:
            for number, line in enumerate(_script_lines(job.get(key, defaults.get(key)))):
                at = (name, key, number) if key in job else ("default", key, number)
                yield from script_facts(
                    substitute_variables(line, variables), job=identity, origin=Origin(path=path, at=at), env=env
                )


def pipeline_facts(path: str, document: object, _: Load | None = None) -> Iterator[Fact]:
    """The jobs of a pipeline, one per `parallel: matrix:` combination, with the commands each one runs."""
    if not isinstance(document, Mapping):
        return
    default = document.get("default")
    defaults = {
        "image": document.get("image"),
        "variables": document.get("variables"),
        **{key: document[key] for key in _SCRIPTS if key in document},
        **(default if isinstance(default, Mapping) else {}),
    }
    for name, job in document.items():
        if _is_job(str(name), job) and isinstance(job, Mapping):
            yield from _job_facts(path, str(name), job, defaults)


GITLAB_CI = CiProvider(
    name="GitLab CI",
    files=(".gitlab-ci.yml",),
    linters=(
        pattern("glab ci lint", r"\bglab\s+ci\s+lint\b"),
        pattern("gitlab-ci-local --preview", r"\bgitlab-ci-local\b[^\n]*--preview\b"),
        pattern("the CI lint API", r"/api/v4/projects/\S*/ci/lint\b"),
    ),
    lint_hint="GitLab CI: run glab ci lint (or gitlab-ci-local --preview) in CI",
    badges=(pattern("GitLab CI", r"/badges/[^\s)\]]+/pipeline\.svg|img\.shields\.io/gitlab/pipeline-status/"),),
    facts=pipeline_facts,
)
