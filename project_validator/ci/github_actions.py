"""GitHub Actions: workflows are parsed, and each job's matrix is expanded the way GitHub expands it."""

import itertools
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

from project_validator.ci import CiProvider, strings
from project_validator.ci.github_expressions import Known, evaluate, rendered
from project_validator.facts import ActionStep, CiJob, Fact, Origin, Unknown
from project_validator.facts.expansion import script_facts
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern

type Combination = dict[str, object]

_MATRIX_EXPRESSION = re.compile(r"\$\{\{\s*matrix\.([\w.-]+)\s*\}\}")
_RESERVED_MATRIX_KEYS = frozenset({"include", "exclude"})


def _lookup(combination: Combination, dotted: str) -> object | None:
    value: object = combination
    for key in dotted.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def substitute_matrix(text: str, combination: Combination, missing: str | None = None) -> str:
    """`text` with `${{ matrix.<key> }}` replaced by the combination's values; a key the combination lacks is left as
    written, or replaced by `missing` (GitHub itself substitutes an empty string)."""

    def replacement(match: re.Match[str]) -> str:
        value = _lookup(combination, match[1])
        if value is None:
            return match[0] if missing is None else missing
        return value if isinstance(value, str) else json.dumps(value)

    return _MATRIX_EXPRESSION.sub(replacement, text)


# An expression GitHub evaluates before the shell runs the step.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


def _is_subset(entry: Mapping[str, object], combination: Combination) -> bool:
    return all(combination.get(key) == value for key, value in entry.items())


def _can_extend(entry: Mapping[str, object], original: Combination) -> bool:
    return all(original[key] == value for key, value in entry.items() if key in original)


def expand_matrix(matrix: object) -> list[Combination] | None:
    """Every combination GitHub would run, or None when the matrix is computed by an expression."""
    if matrix is None:
        return [{}]
    if not isinstance(matrix, Mapping):
        return None
    base = {key: value for key, value in matrix.items() if key not in _RESERVED_MATRIX_KEYS}
    includes = matrix.get("include", [])
    excludes = matrix.get("exclude", [])
    vectors = (*base.values(), includes, excludes)
    if not all(isinstance(vector, list) for vector in vectors):
        return None

    originals = [dict(zip(base, values, strict=True)) for values in itertools.product(*base.values())] if base else []
    originals = [c for c in originals if not any(_is_subset(entry, c) for entry in excludes)]
    return _with_includes(originals, includes) if base or includes else [{}]


def _with_includes(originals: list[Combination], includes: list[Mapping[str, object]]) -> list[Combination]:
    """GitHub's include rules: extend every original combination an entry fits, else add the entry as its own."""
    expanded = [dict(original) for original in originals]
    additions: list[Combination] = []
    for entry in includes:
        targets = [result for original, result in zip(originals, expanded, strict=True) if _can_extend(entry, original)]
        for target in targets:
            target.update(entry)
        if not targets:
            additions.append(dict(entry))
    return expanded + additions


def _runner_os(job: Mapping[str, object], combination: Combination) -> str:
    if "container" in job:
        return "linux"
    runner = substitute_matrix(json.dumps(job.get("runs-on", "")), combination)
    found = detect_operating_systems(runner)
    return found[0] if found else "unknown"


def _combination_label(combination: Combination) -> str:
    return ", ".join(value if isinstance(value, str) else json.dumps(value) for value in combination.values())


def _job_label(name: str, combination: Combination) -> str:
    substituted = substitute_matrix(name, combination)
    if substituted != name or not combination:
        return substituted
    return f"{name} ({_combination_label(combination)})"


def _job_facts(path: str, job_id: str, job: Mapping[str, object], workflow_env: object) -> Iterator[Fact]:
    origin = Origin(path=path, at=("jobs", job_id))
    strategy = job.get("strategy")
    combinations = expand_matrix(strategy.get("matrix") if isinstance(strategy, Mapping) else None)
    if combinations is None:
        name = f"{job.get('name', job_id)} (matrix computed by an expression)"
        yield CiJob(origin=origin, id=f"{path}:{job_id}", provider=GITHUB_ACTIONS.name, name=name, os="unknown")
        yield Unknown(origin=origin, subject=f"the matrix of job {job_id}", reason="it is computed by an expression")
        return
    for index, combination in enumerate(combinations):
        identity = f"{path}:{job_id}" if len(combinations) == 1 else f"{path}:{job_id}[{index}]"
        yield from _Combination(origin, identity, combination).facts(job, workflow_env)


@dataclass(frozen=True, slots=True)
class _Combination:
    """One matrix combination of a job, whose values are substituted into everything the job runs."""

    origin: Origin
    identity: str
    combination: Combination
    # What the job's conditions and expressions can be evaluated with, once its environment is known.
    known: Known | None = None

    def substitute(self, text: str) -> str:
        """`text` as GitHub runs it: matrix values in place, and every expression whose value is known evaluated."""
        text = substitute_matrix(text, self.combination, missing="")
        if (known := self.known) is None:
            return text
        return EXPRESSION.sub(
            lambda match: value if (value := rendered(match[0], known)) is not None else match[0], text
        )

    def substituted(self, value: object) -> dict[str, str]:
        return {key: self.substitute(text) for key, text in strings(value).items()}

    def optional(self, value: object) -> str | None:
        return self.substitute(value) if isinstance(value, str) else None

    def runs(self, condition: object, known: Known) -> bool | None:
        """Whether a job or step with `condition` runs in this combination; None when the checkout does not show it.

        A condition that is not a string (`if: true`) is YAML's own value."""
        if condition is None:
            return True
        return evaluate(condition, known) if isinstance(condition, str) else bool(condition)

    def facts(self, job: Mapping[str, object], workflow_env: object) -> Iterator[Fact]:
        env = {**self.substituted(workflow_env), **self.substituted(job.get("env"))}
        os = _runner_os(job, self.combination)
        known = Known(os=os, matrix=self.combination, env=env)
        if self.runs(job.get("if"), known) is False:
            return
        yield from replace(self, known=known).job_facts(job, known)

    def job_facts(self, job: Mapping[str, object], known: Known) -> Iterator[Fact]:
        container = job.get("container")
        yield CiJob(
            origin=self.origin,
            id=self.identity,
            provider=GITHUB_ACTIONS.name,
            name=_job_label(str(job.get("name", self.origin.at[-1])), self.combination),
            os=known.os,
            matrix={
                key: value if isinstance(value, str) else json.dumps(value) for key, value in self.combination.items()
            },
            image=self.optional(container.get("image") if isinstance(container, Mapping) else container),
            env=self.substituted(known.env),
        )
        steps = job.get("steps")
        for number, step in enumerate(steps if isinstance(steps, list) else []):
            if isinstance(step, Mapping):
                yield from self.step_facts(
                    Origin(path=self.origin.path, at=(*self.origin.at, "steps", number)), step, known
                )

    def step_facts(self, origin: Origin, step: Mapping[str, object], known: Known) -> Iterator[Fact]:
        """The facts of a step that runs, or may run, in this combination; its condition is kept while unknown."""
        runs = self.runs(step.get("if"), known)
        if runs is False:
            return
        condition = None if runs else self.optional(step.get("if"))
        if "uses" in step:
            inputs = self.substituted(step.get("with"))
            yield ActionStep(
                origin=origin, job=self.identity, uses=str(step["uses"]), inputs=inputs, condition=condition
            )
        if isinstance(run := step.get("run"), str):
            yield from script_facts(
                self.substitute(run),
                job=self.identity,
                origin=Origin(path=origin.path, at=(*origin.at, "run")),
                env={**known.env, **self.substituted(step.get("env"))},
                directory=self.optional(step.get("working-directory")),
                condition=condition,
                opaque=EXPRESSION,
            )


def workflow_facts(path: str, document: object) -> Iterator[Fact]:
    """The jobs of a workflow, one per matrix combination, with the commands and actions each one runs."""
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        if "uses" in job:
            yield Unknown(
                origin=Origin(path=path, at=("jobs", str(job_id))),
                subject=f"job {job_id}",
                reason=f"it calls the reusable workflow {job['uses']}, which is not read",
            )
            continue
        yield from _job_facts(path, str(job_id), job, document.get("env"))


def _uses(entries: object) -> list[str]:
    if not isinstance(entries, list):
        return []
    return [str(entry["uses"]) for entry in entries if isinstance(entry, Mapping) and "uses" in entry]


def action_references(document: object) -> list[str]:
    """Every reusable workflow (`jobs.<id>.uses`) and action (`jobs.<id>.steps[*].uses`) a workflow uses."""
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return []
    found = [job for job in jobs.values() if isinstance(job, Mapping)]
    return [*_uses(found), *(reference for job in found for reference in _uses(job.get("steps")))]


GITHUB_ACTIONS = CiProvider(
    name="GitHub Actions",
    directories=(".github/workflows",),
    # zizmor also finds security problems in workflows: template injection, credentials persisted by checkout, ...
    linters=(pattern("actionlint", r"\bactionlint\b"), pattern("zizmor", r"\bzizmor\b")),
    lint_hint="GitHub Actions: run actionlint (rhysd/actionlint) or zizmor (zizmorcore/zizmor-action) in CI",
    badges=(
        pattern(
            "GitHub Actions",
            r"/actions/workflows/[^/\s]+/badge\.svg|/workflows/[^/\s]+/badge\.svg|img\.shields\.io/github/actions/workflow/status/",
        ),
    ),
    step_references=action_references,
    facts=workflow_facts,
)
