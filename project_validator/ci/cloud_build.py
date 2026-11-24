"""Google Cloud Build: a build config read as one job of steps, each a command in its own image (upstream #223).

A config is `cloudbuild.yaml` (or `.yml`) at the top of the project, or a `*.cloudbuild.yaml` there or in `build/`,
where the Cloud Foundation Toolkit's repositories keep theirs (`build/int.cloudbuild.yaml`); a trigger may name any
other file, which is not found. Every step runs on Linux. A step runs its `script` (a shell script), or else its
`entrypoint` with its `args`, or else, for one of Google's builders (`gcr.io/cloud-builders/go`), the builder's tool
with its `args`, or else its `args` as the command. `$_NAME` and `${_NAME}` take the defaults of `substitutions:`, and
`$$` is a `$`; a step that `allowFailure`s cannot fail the build.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from project_validator.ci import CiProvider, Load, strings
from project_validator.facts import CiJob, Fact, Origin
from project_validator.facts.exit_status import shell_of
from project_validator.facts.expansion import advised, script_facts
from project_validator.facts.shell import command_line
from project_validator.tools.shell_scripts import interpreter

_SUBSTITUTION = re.compile(r"\$\$|\$\{(_\w+)\}|\$(_\w+)")
_BUILDER = re.compile(r"^gcr\.io/cloud-builders/(?P<tool>[\w-]+)(?:[:@].*)?$")


def _substituted(text: str, substitutions: Mapping[str, str]) -> str:
    def value(match: re.Match[str]) -> str:
        if match[0] == "$$":
            return "$"
        return substitutions.get(match[1] or match[2], match[0])

    return _SUBSTITUTION.sub(value, text)


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _words(step: Mapping[str, object], substitutions: Mapping[str, str]) -> list[str]:
    """The command a step without a script runs: its entrypoint, or its builder's tool, then its args."""
    args = [_substituted(str(arg), substitutions) for arg in _list(step.get("args")) if isinstance(arg, (str, int))]
    if isinstance(step.get("entrypoint"), str):
        return [_substituted(str(step["entrypoint"]), substitutions), *args]
    builder = _BUILDER.match(str(step.get("name", "")))
    return [builder["tool"], *args] if builder else args


def _environment(step: Mapping[str, object], substitutions: Mapping[str, str]) -> dict[str, str]:
    pairs = (_substituted(str(line), substitutions).partition("=") for line in _list(step.get("env")))
    return {name: value for name, sign, value in pairs if sign}


def _step_facts(path: str, index: int, step: Mapping[str, object], substitutions: Mapping[str, str]) -> Iterator[Fact]:
    env = _environment(step, substitutions)
    directory = _substituted(str(step["dir"]), substitutions) if isinstance(step.get("dir"), str) else None
    if isinstance(step.get("script"), str):
        script = str(step["script"])
        facts = script_facts(
            script,
            job=path,
            origin=Origin(path=path, at=("steps", index, "script")),
            env=env,
            directory=directory,
            shell=shell_of(interpreter(script) or "sh"),
        )
    elif words := _words(step, substitutions):
        facts = script_facts(
            command_line(words), job=path, origin=Origin(path=path, at=("steps", index)), env=env, directory=directory
        )
    else:
        return
    yield from advised(facts, "allowFailure" if step.get("allowFailure") is True else "")


def cloud_build_facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    """The build as one Linux job, with the command of each step."""
    if not isinstance(document, Mapping):
        return
    substitutions = strings(document.get("substitutions"))
    yield CiJob(origin=Origin(path=path), id=path, provider=CLOUD_BUILD.name, name=path, os="linux")
    steps = document.get("steps")
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        if isinstance(step, Mapping):
            yield from _step_facts(path, index, step, substitutions)


CLOUD_BUILD = CiProvider(
    name="Google Cloud Build",
    files=("cloudbuild.yaml", "cloudbuild.yml"),
    directories=(".", "build"),
    suffixes=(".cloudbuild.yaml", ".cloudbuild.yml"),
    facts=cloud_build_facts,
)
