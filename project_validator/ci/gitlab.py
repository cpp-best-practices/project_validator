"""GitLab CI: jobs are parsed, `parallel: matrix:` is expanded and the runner OS comes from the job's tags.

The pipeline is the main file with the local files it includes (`include: /ci/build.yml` or `local:`) merged in, the
main file's keys over theirs. A job's `extends:` merges its templates first, mappings deep and everything else
replaced, as GitLab merges them; a `!reference [.job, key]` is replaced by the value it names. Includes from other
projects, URLs or templates are not read.
"""

import itertools
import json
import re
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Command, Fact, Origin, Unknown
from project_validator.facts.expansion import script_facts
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern
from project_validator.yaml_support import Tagged

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


def _image(job: Mapping[str, object], defaults: Mapping[str, object]) -> object:
    image = job.get("image", defaults.get("image"))
    return image.get("name") if isinstance(image, Mapping) else image


def _scripts(
    path: str, name: str, job: Mapping[str, object], defaults: Mapping[str, object]
) -> Iterator[tuple[str, Origin]]:
    """Each script line the job runs (its own, else the default's), where it is written."""
    for key in _SCRIPTS:
        for number, line in enumerate(_script_lines(job.get(key, defaults.get(key)))):
            yield line, Origin(path=path, at=(name, key, number) if key in job else ("default", key, number))


def _job_facts(path: str, name: str, job: Mapping[str, object], defaults: Mapping[str, object]) -> Iterator[Fact]:
    image_name = _image(job, defaults)
    tags = json.dumps(job.get("tags", defaults.get("tags", [])), default=str)
    combinations = expand_parallel(job.get("parallel"))
    for index, variables in enumerate(combinations):
        identity = f"{path}:{name}" if len(combinations) == 1 else f"{path}:{name}[{index}]"
        env = {**strings(defaults.get("variables")), **strings(job.get("variables")), **variables}
        os = _runner_os(substitute_variables(tags, variables))
        yield CiJob(
            origin=Origin(path=path, at=(name,)),
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
        for line, origin in _scripts(path, name, job, defaults):
            # A Windows runner's shell is PowerShell.
            text = substitute_variables(line, variables)
            yield from script_facts(text, job=identity, origin=origin, env=env, powershell=os == "windows")


# GitLab reads at most this many levels of nested includes, and of extends.
_DEPTH = 10


def _merged(base: Mapping[str, object], over: Mapping[str, object]) -> dict[str, object]:
    """`over` merged into `base` as GitLab merges configuration: mappings deep, every other value replaced."""
    merged = dict(base)
    for key, value in over.items():
        below = merged.get(key)
        merged[key] = _merged(below, value) if isinstance(below, Mapping) and isinstance(value, Mapping) else value
    return merged


def _local_include(entry: object) -> str | None:
    """The path of a local include (`/ci/build.yml`, `{local: ci/build.yml}`), relative to the project; a glob is
    not one."""
    path = entry.get("local") if isinstance(entry, Mapping) else entry if isinstance(entry, str) else None
    if not isinstance(path, str) or "://" in path or "*" in path:
        return None
    return path.lstrip("/")


# GitLab's templates whose jobs are known by what they do (security scanners), though their commands are not read.
_KNOWN_TEMPLATES = re.compile(
    r"(?:Security|Jobs)/(?:SAST|SAST-IaC|Secret-Detection|Dependency-Scanning|Container-Scanning)(?:\.latest)?\.gitlab-ci\.yml"
)


def _known_template(entry: object) -> str | None:
    template = entry.get("template") if isinstance(entry, Mapping) else None
    return template if isinstance(template, str) and _KNOWN_TEMPLATES.fullmatch(template) else None


def _template_facts(path: str, index: int, template: str) -> Iterator[Fact]:
    """The jobs a known template adds: one job, which builds nothing, running the template as a marker command
    (`gitlab-template Security/SAST.gitlab-ci.yml`) that the tools it runs claim."""
    origin = Origin(path=path, at=("include", index))
    identity = f"{path}:template:{template}"
    yield CiJob(origin=origin, id=identity, provider=GITLAB_CI.name, name=template, os="linux", builds=False)
    yield Command(origin=origin, job=identity, argv=("gitlab-template", template), line=f"template: {template}")


def _include_entries(document: Mapping[str, object]) -> list[object]:
    includes = document.get("include")
    return includes if isinstance(includes, list) else [] if includes is None else [includes]


type _Pipeline = tuple[dict[str, object], dict[str, str], list[Fact]]


def _included(path: str, document: Mapping[str, object], load: Load | None, depth: int = 0) -> _Pipeline:
    """The pipeline: `document` over the local files it includes; the file that defines each top-level key; and the
    facts of the includes that are not merged (the jobs of known templates, and unknowns for the others)."""
    pipeline: dict[str, object] = {}
    sources: dict[str, str] = {}
    unread: list[Fact] = []
    for index, entry in enumerate(_include_entries(document)):
        if (template := _known_template(entry)) is not None:
            unread.extend(_template_facts(path, index, template))
            continue
        local = _local_include(entry)
        found = load(local) if local is not None and load is not None and depth < _DEPTH else None
        if local is None or not isinstance(found, Mapping):
            subject = f"the include {json.dumps(entry, default=str)}"
            origin = Origin(path=path, at=("include", index))
            unread.append(Unknown(origin=origin, subject=subject, reason="it is not read", hides="jobs"))
            continue
        nested, nested_sources, nested_unread = _included(local, found, load, depth + 1)
        pipeline, unread = _merged(pipeline, nested), [*unread, *nested_unread]
        sources.update(nested_sources)
    own = {str(key): value for key, value in document.items() if key != "include"}
    sources.update(dict.fromkeys(own, path))
    return _merged(pipeline, own), sources, unread


def _extended(name: str, pipeline: Mapping[str, object], depth: int = 0) -> Mapping[str, object] | None:
    """Job `name` with the templates it `extends` merged in first; None when one of them is not defined."""
    job = pipeline.get(name)
    if not isinstance(job, Mapping):
        return None
    parents = job.get("extends")
    names = parents if isinstance(parents, list) else [] if parents is None else [parents]
    merged: dict[str, object] = {}
    for parent in map(str, names):
        base = _extended(parent, pipeline, depth + 1) if depth < _DEPTH else None
        if base is None:
            return None
        merged = _merged(merged, base)
    return _merged(merged, {key: value for key, value in job.items() if key != "extends"})


def _referenced(value: object, pipeline: Mapping[str, object], depth: int = 0) -> object:
    """`value` with each `!reference [.job, key, ...]` replaced by what it names; in a list, a referenced list's
    items take its place."""
    if isinstance(value, Tagged) and value.tag == "!reference" and isinstance(value.value, list) and depth < _DEPTH:
        found: object = pipeline
        for key in map(str, value.value):
            found = found.get(key) if isinstance(found, Mapping) else None
        return _referenced(found, pipeline, depth + 1)
    if isinstance(value, list):
        items = (_referenced(item, pipeline, depth) for item in value)
        return [part for item in items for part in (item if isinstance(item, list) else [item])]
    if isinstance(value, Mapping):
        return {key: _referenced(item, pipeline, depth) for key, item in value.items()}
    return value


def _referenced_mapping(value: Mapping[str, object], pipeline: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _referenced(item, pipeline) for key, item in value.items()}


def pipeline_facts(path: str, document: object, load: Load | None = None) -> Iterator[Fact]:
    """The jobs of a pipeline, one per `parallel: matrix:` combination, with the commands each one runs."""
    if not isinstance(document, Mapping):
        return
    pipeline, sources, unread = _included(path, document, load)
    yield from unread
    default = pipeline.get("default")
    defaults = _referenced_mapping(
        {
            "image": pipeline.get("image"),
            "variables": pipeline.get("variables"),
            **{key: pipeline[key] for key in _SCRIPTS if key in pipeline},
            **(default if isinstance(default, Mapping) else {}),
        },
        pipeline,
    )
    for name, job in pipeline.items():
        if not _is_job(name, job):
            continue
        resolved = _extended(name, pipeline)
        if resolved is None:
            origin = Origin(path=sources.get(name, path), at=(name,))
            yield Unknown(origin=origin, subject=f"job {name}", reason="a template it extends is not defined")
            continue
        yield from _job_facts(sources.get(name, path), name, _referenced_mapping(resolved, pipeline), defaults)


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
