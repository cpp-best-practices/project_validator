"""GitHub Actions: workflows are parsed, and each job's matrix is expanded the way GitHub expands it."""

import itertools
import json
import re
from collections.abc import Mapping

from project_validator.ci import CiProvider, Job, build_job
from project_validator.platforms import detect_operating_systems

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


def substitute_matrix(text: str, combination: Combination) -> str:
    def replacement(match: re.Match[str]) -> str:
        value = _lookup(combination, match[1])
        if value is None:
            return match[0]
        return value if isinstance(value, str) else json.dumps(value)

    return _MATRIX_EXPRESSION.sub(replacement, text)


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
    expanded = [dict(original) for original in originals]
    additions: list[Combination] = []
    for entry in includes:
        targets = [result for original, result in zip(originals, expanded, strict=True) if _can_extend(entry, original)]
        for target in targets:
            target.update(entry)
        if not targets:
            additions.append(dict(entry))
    return expanded + additions if base or includes else [{}]


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


def _job_text(job: Mapping[str, object]) -> str:
    return json.dumps({key: value for key, value in job.items() if key != "strategy"}, default=str)


def _expand_job(job_id: str, job: Mapping[str, object]) -> list[Job]:
    name = str(job.get("name", job_id))
    strategy = job.get("strategy")
    combinations = expand_matrix(strategy.get("matrix") if isinstance(strategy, Mapping) else None)
    if combinations is None:
        return [Job(name=f"{name} (matrix computed by an expression)", os="unknown", compilers=frozenset())]

    text = _job_text(job)
    return [
        build_job(
            _job_label(name, combination),
            _runner_os(job, combination),
            json.dumps(combination, default=str),
            substitute_matrix(text, combination),
        )
        for combination in combinations
    ]


def parse_workflow(document: object) -> list[Job]:
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return []
    return [
        expanded
        for job_id, job in jobs.items()
        if isinstance(job, Mapping) and "uses" not in job
        for expanded in _expand_job(str(job_id), job)
    ]


GITHUB_ACTIONS = CiProvider(name="GitHub Actions", directories=(".github/workflows",), parse_yaml=parse_workflow)
