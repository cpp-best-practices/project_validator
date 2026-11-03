"""GitLab CI: jobs are parsed, `parallel: matrix:` is expanded and the runner OS comes from the job's tags."""

import itertools
import json
import re
from collections.abc import Mapping

from project_validator.ci import CiProvider, Job, build_job
from project_validator.platforms import detect_operating_systems

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


def _expand_combination(name: str, job: Mapping[str, object], image: str, tags: str, variables: Variables) -> Job:
    os = _runner_os(substitute_variables(tags, variables))
    image_text = image if os == "linux" else ""  # only Linux runners run jobs in Docker images
    return build_job(
        f"{name} ({', '.join(variables.values())})" if variables else name,
        os,
        json.dumps(variables),
        substitute_variables(f"{image_text} {json.dumps(dict(job), default=str)}", variables),
    )


def _expand_job(name: str, job: Mapping[str, object], defaults: Mapping[str, object]) -> list[Job]:
    image = json.dumps(job.get("image", defaults.get("image", "")), default=str)
    tags = json.dumps(job.get("tags", defaults.get("tags", [])), default=str)
    return [
        _expand_combination(name, job, image, tags, variables) for variables in expand_parallel(job.get("parallel"))
    ]


def parse_pipeline(document: object) -> list[Job]:
    if not isinstance(document, Mapping):
        return []
    default = document.get("default")
    defaults = {"image": document.get("image", ""), **(default if isinstance(default, Mapping) else {})}
    return [
        expanded
        for name, job in document.items()
        if _is_job(str(name), job)
        for expanded in _expand_job(str(name), job, defaults)
    ]


GITLAB_CI = CiProvider(name="GitLab CI", files=(".gitlab-ci.yml",), parse_yaml=parse_pipeline)
