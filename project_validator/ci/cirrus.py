"""Cirrus CI: `.cirrus.yml` read as its tasks and the commands of their scripts.

A task is a top-level `task:` or `<name>_task:` (Cirrus lets `task:` be written more than once, and each is read), or
a `docker_builder:` or `<name>_docker_builder:`, which runs on a Linux machine with Docker. Its name is its `name:`,
else the key's prefix, else `main`, as Cirrus names it. It runs on the instance it names, else the one written at the
top: `container`, `arm_container` and docker builders on Linux (a container's `image` is the job's image),
`macos_instance` on macOS, `windows_container` on Windows, `freebsd_instance` on FreeBSD, a `compute_engine_instance`
or docker builder on its `platform` (Linux by default), and any other (`persistent_worker`) on an unknown OS. Each leg
of a task's `matrix:`, a list of mappings over the task's keys (their `env:` merged), is a task of its own.

`env:`, the top's and the task's, is the scripts' environment. A `script:` or `<name>_script:`, text or a list of
lines, runs in order: on Unix under `set -e` and `set -o pipefail`, as Cirrus's agent writes it, and on Windows in
cmd, which stops the task at a line that fails. A `<name>_background_script` cannot fail the task, nor can any script
of a task that `allow_failures`. Starlark configurations (`.cirrus.star`) are not read.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from project_validator import yaml_support
from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin
from project_validator.facts.exit_status import STRICT
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import CMD, POSIX
from project_validator.text import pattern

_TASK = re.compile(r"^(?:(?P<name>\w+?)_)?(?P<kind>task|docker_builder)$")
# The instances whose OS their key says; a container's image is the job's.
_INSTANCES = {
    "container": "linux",
    "arm_container": "linux",
    "gke_container": "linux",
    "macos_instance": "macos",
    "osx_instance": "macos",
    "windows_container": "windows",
    "freebsd_instance": "freebsd",
}
_INSTANCE = re.compile(r"_(?:instance|container)$|^persistent_worker$")
_PLATFORMS = {"linux": "linux", "windows": "windows", "freebsd": "freebsd", "darwin": "macos"}
_BACKGROUND = "it runs in the background"


def _platform(instance: object) -> str:
    platform = instance.get("platform", "linux") if isinstance(instance, Mapping) else "linux"
    return _PLATFORMS.get(str(platform).lower(), "unknown")


def _where(task: Mapping[str, object], top: Mapping[str, object], docker: bool) -> tuple[str, str | None]:
    """The OS a task runs on, and the image of its container: of the instance it names, else of the top's."""
    if docker:
        return _platform(task), None
    for source in (task, top):
        for key, instance in source.items():
            if key in _INSTANCES:
                image = instance.get("image") if isinstance(instance, Mapping) and key.endswith("container") else None
                return _INSTANCES[key], None if image is None else str(image)
            if key == "compute_engine_instance":
                return _platform(instance), None
            if _INSTANCE.search(key):
                return "unknown", None
    return "unknown", None


def _legs(task: Mapping[str, object]) -> list[dict[str, object]]:
    """A task, or each leg of its matrix over it, its `env:` merged with the leg's."""
    matrix = task.get("matrix")
    base = {key: value for key, value in task.items() if key != "matrix"}
    if not isinstance(matrix, list):
        return [base]
    legs = (leg for leg in matrix if isinstance(leg, Mapping))
    return [{**base, **leg, "env": {**strings(base.get("env")), **strings(leg.get("env"))}} for leg in legs] or [base]


def _script(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(line) for line in value if isinstance(line, (str, int, float)))
    return None


def _task_facts(
    path: str, at: str, identity: str, task: Mapping[str, object], env: Mapping[str, str], os: str
) -> Iterator[Fact]:
    failing = "allow_failures" if task.get("allow_failures") is True else ""
    for key, value in task.items():
        if not (key == "script" or key.endswith("_script")) or (script := _script(value)) is None:
            continue
        windows = os == "windows"
        facts = script_facts(
            script,
            job=identity,
            origin=Origin(path=path, at=(at, key)),
            env=env,
            dialect=CMD if windows else POSIX,
            shell=None if windows else STRICT,
        )
        yield from advised(facts, _BACKGROUND if key.endswith("_background_script") else failing)


def _pairs(document: object) -> list[tuple[str, object]]:
    found = document.items() if isinstance(document, Mapping) else document if isinstance(document, list) else ()
    return [(str(pair[0]), pair[1]) for pair in found if isinstance(pair, tuple) and len(pair) == 2]


def cirrus_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """Each task, one per leg of its matrix, with the commands of its scripts."""
    pairs = _pairs(document)
    top = {key: value for key, value in pairs if not _TASK.match(key)}
    seen: dict[str, int] = {}
    for key, task in pairs:
        if (kind := _TASK.match(key)) is None or not isinstance(task, Mapping):
            continue
        for leg in _legs({str(name): value for name, value in task.items()}):
            name = str(leg.get("name") or kind["name"] or "main")
            seen[name] = seen.get(name, 0) + 1
            identity = f"{path}:{name}" + (f"[{seen[name]}]" if seen[name] > 1 else "")
            os, image = _where(leg, top, kind["kind"] == "docker_builder")
            env = {**strings(top.get("env")), **strings(leg.get("env"))}
            origin = Origin(path=path, at=(key,))
            yield CiJob(origin=origin, id=identity, provider=CIRRUS_CI.name, name=name, os=os, image=image, env=env)
            yield from _task_facts(path, key, identity, leg, env, os)


CIRRUS_CI = CiProvider(
    name="Cirrus CI",
    files=(".cirrus.yml",),
    badges=(pattern("Cirrus CI", r"api\.cirrus-ci\.com/github/\S+\.svg|img\.shields\.io/cirrus/"),),
    facts=cirrus_facts,
    parse=yaml_support.load_pairs,
)
