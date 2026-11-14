"""GitHub Actions: workflows are parsed, and each job's matrix is expanded the way GitHub expands it."""

from __future__ import annotations

import itertools
import json
import re
import shlex
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace

from project_validator.ci import REPOSITORY, CiProvider, Load, strings
from project_validator.ci.github_expressions import Known, evaluate, rendered
from project_validator.facts import ActionStep, CiJob, Command, Fact, Origin, Unknown
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

# The shells whose scripts are split into commands; another `shell:` names a program that runs the step's script as a
# whole (`python {0}`, `Rscript {0}`).
_SHELLS = frozenset({"bash", "sh", "pwsh", "powershell", "cmd"})


def custom_shell(shell: str | None) -> tuple[str, ...] | None:
    """The command line of a step's custom shell (`shell: Rscript {0}`, `julia --color=yes {0}`), with `{0}` where
    GitHub puts the script's file; None for a shell GitHub knows (whose script is split into commands), or none."""
    if shell is None:
        return None
    try:
        words = shlex.split(shell)
    except ValueError:
        words = shell.split()
    if not words or words[0] in _SHELLS or _runs_a_shell(words):
        return None
    return tuple(words) if "{0}" in words else (*words, "{0}")


# A wrapper that runs the script with a shell GitHub knows: msys2's shell (setup-msys2), or a word that is such a
# shell running `{0}` (`script -q -e -c "bash {0}"`, which gives the script a terminal).
_SHELL_OF_SCRIPT = re.compile(r"(?:ba|z|da|k)?sh(?:\s+-\w+)*\s+\{0\}")


def _runs_a_shell(words: list[str]) -> bool:
    return words[0] == "msys2" or any(_SHELL_OF_SCRIPT.fullmatch(word) for word in words)


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
    # What is left is an expression over the matrix (`matrix.os || 'ubuntu-latest'`): its value names the runner.
    known = Known(os="unknown", matrix=combination, env={})
    runner = EXPRESSION.sub(lambda match: rendered(match[0][3:-2], known) or match[0], runner)
    found = detect_operating_systems(runner)
    return found[0] if found else "unknown"


def _combination_label(combination: Combination) -> str:
    return ", ".join(value if isinstance(value, str) else json.dumps(value) for value in combination.values())


def _job_label(name: str, combination: Combination, substitute: Callable[[str], str]) -> str:
    """The job's name as GitHub shows it: its expressions evaluated and its lines folded into one; a name with no
    expression in it is followed by the matrix combination's values."""
    shown = " ".join(substitute(name).split())
    if EXPRESSION.search(name) or not combination:
        return shown
    return f"{shown} ({_combination_label(combination)})"


_EXPORT = re.compile(
    r"""(?:^|[;&]\s*)\s*(?:echo|printf)\s+(?:-\w+\s+)?["']?(?P<name>[A-Za-z_]\w*)=(?P<value>[^"'\n]*?)["']?"""
    r"""\s*>>\s*["']?\$\{?GITHUB_ENV\}?["']?\s*$""",
    re.MULTILINE,
)


_ASSIGNMENT = re.compile(r"(?:^|[;&]\s*)\s*(?:export\s+)?(?P<name>[A-Za-z_]\w*)=(?P<value>[^\s;&|]*)", re.MULTILINE)
_REFERENCE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def _exported(script: str) -> dict[str, str]:
    """The variables a step's script sets for the later steps (`echo "NAME=value" >> "$GITHUB_ENV"`), with the
    variables the script assigns before in place (`HC=/opt/ghc/bin/ghc` then `echo "HC=$HC" >> "$GITHUB_ENV"`)."""
    exported: dict[str, str] = {}
    for match in _EXPORT.finditer(script):
        if _conditional(script, match.start() + match[0].index(match[0].lstrip(";& \t\n"))):
            continue  # set only sometimes (zls's `if …; then echo "SKIP=true" >> $GITHUB_ENV; fi`): not known
        assigned = {
            found["name"]: found["value"].strip("\"'") for found in _ASSIGNMENT.finditer(script, 0, match.start())
        }
        exported[match["name"]] = _substituted(match["value"], assigned)
    return exported


_OPENS = re.compile(r"(?:^|[;&|]\s*)\s*(?:if|case|while|until|for)\b", re.MULTILINE)
_CLOSES = re.compile(r"(?:^|[;&|]\s*)\s*(?:fi|esac|done)\b", re.MULTILINE)


def _conditional(script: str, at: int) -> bool:
    """Whether the command at `at` runs only sometimes: inside an `if`, `case` or loop, or after `&&` or `||`."""
    before = script[:at]
    if re.search(r"(?:&&|\|\|)\s*$", before):
        return True
    return len(_OPENS.findall(before)) > len(_CLOSES.findall(before))


def _substituted(value: str, assigned: Mapping[str, str]) -> str:
    return _REFERENCE.sub(lambda reference: assigned.get(reference[1] or reference[2], reference[0]), value)


def _job_facts(
    path: str,
    job_id: str,
    job: Mapping[str, object],
    workflow: Mapping[str, object],
    caller: str = "",
    load: Load | None = None,
) -> Iterator[Fact]:
    """The facts of one job; `caller` names the job that calls the workflow, for a reusable workflow's jobs. `load`
    reads the local actions its steps use."""
    origin = Origin(path=path, at=("jobs", job_id))
    strategy = job.get("strategy")
    combinations = expand_matrix(strategy.get("matrix") if isinstance(strategy, Mapping) else None)
    if combinations is None:
        # Its steps still run, in combinations that are not known: their matrix values stay as written.
        yield Unknown(
            origin=origin,
            subject=f"the matrix of job {job_id}",
            reason="it is computed by an expression",
            hides="matrix",
        )
        unknown = _Combination(origin, f"{caller}{path}:{job_id}", {}, load=load, matrix_known=False)
        yield from unknown.facts(job, workflow)
        return
    for index, combination in enumerate(combinations):
        identity = f"{caller}{path}:{job_id}" + ("" if len(combinations) == 1 else f"[{index}]")
        yield from _Combination(origin, identity, combination, load=load).facts(job, workflow)


@dataclass(frozen=True, slots=True)
class _Combination:
    """One matrix combination of a job, whose values are substituted into everything the job runs."""

    origin: Origin
    identity: str
    combination: Combination
    # What the job's conditions and expressions can be evaluated with, once its environment is known.
    known: Known | None = None
    load: Load | None = None
    # Whether the combination's values are known; when not, matrix expressions stay as written.
    matrix_known: bool = True
    # The shell the job's steps run in unless a step names its own (`defaults: run: shell:`).
    shell: str | None = None
    # The directory the job's `run` steps run in unless a step names its own (`defaults: run: working-directory:`).
    working_directory: str | None = None

    def substitute(self, text: str) -> str:
        """`text` as GitHub runs it: matrix values in place, and every expression whose value is known evaluated."""
        text = substitute_matrix(text, self.combination, missing="" if self.matrix_known else None)
        if (known := self.known) is None:
            return text
        return EXPRESSION.sub(
            lambda match: value if (value := rendered(match[0], known)) is not None else match[0], text
        )

    def substituted(self, value: object) -> dict[str, str]:
        return {key: self.substitute(text) for key, text in strings(value).items()}

    def optional(self, value: object) -> str | None:
        return self.substitute(value) if isinstance(value, str) else None

    def _services(self, services: object) -> tuple[str, ...]:
        """The images of a job's service containers: `services: {postgres: {image: postgres:16}}`, or an image alone."""
        if not isinstance(services, Mapping):
            return ()
        images = (
            self.optional(service.get("image") if isinstance(service, Mapping) else service)
            for service in services.values()
        )
        return tuple(image for image in images if image)

    def runs(self, condition: object, known: Known) -> bool | None:
        """Whether a job or step with `condition` runs in this combination; None when the checkout does not show it.

        A condition that is not a string (`if: true`) is YAML's own value."""
        if condition is None:
            return True
        return evaluate(condition, known) if isinstance(condition, str) else bool(condition)

    def facts(self, job: Mapping[str, object], workflow: Mapping[str, object]) -> Iterator[Fact]:
        env = {**self.substituted(workflow.get("env")), **self.substituted(job.get("env"))}
        os = _runner_os(job, self.combination)
        known = Known(os=os, matrix=self.combination, env=env, matrix_known=self.matrix_known)
        if self.runs(job.get("if"), known) is False:
            return
        # `defaults: run:` of the workflow, then of the job.
        run = {**_run_defaults(workflow), **_run_defaults(job)}
        shell, directory = run.get("shell"), run.get("working-directory")
        context = replace(self, known=known, shell=str(shell) if shell else None)
        yield from replace(context, working_directory=self.optional(directory)).job_facts(job, known)

    def job_facts(self, job: Mapping[str, object], known: Known) -> Iterator[Fact]:
        container = job.get("container")
        yield CiJob(
            origin=self.origin,
            id=self.identity,
            provider=GITHUB_ACTIONS.name,
            name=_job_label(str(job.get("name", self.origin.at[-1])), self.combination, self.substitute)
            + ("" if self.matrix_known else " (matrix computed by an expression)"),
            os=known.os,
            matrix={
                key: value if isinstance(value, str) else json.dumps(value) for key, value in self.combination.items()
            },
            image=self.optional(container.get("image") if isinstance(container, Mapping) else container),
            services=self._services(job.get("services")),
            env=self.substituted(known.env),
        )
        steps = job.get("steps")
        for number, step in enumerate(steps if isinstance(steps, list) else []):
            if isinstance(step, Mapping):
                yield from self.step_facts(
                    Origin(path=self.origin.path, at=(*self.origin.at, "steps", number)), step, known
                )
                # What a step writes to $GITHUB_ENV is in the environment of the job's later steps.
                if isinstance(run := step.get("run"), str) and (exported := _exported(self.substitute(run))):
                    known = replace(known, env={**known.env, **exported})

    def step_facts(
        self, origin: Origin, step: Mapping[str, object], known: Known, via: tuple[Origin, ...] = ()
    ) -> Iterator[Fact]:
        """The facts of a step that runs, or may run, in this combination; its condition is kept while unknown. A local
        composite action's steps run in the job too, with `via` naming the steps that use it."""
        runs = self.runs(step.get("if"), known)
        if runs is False:
            return
        condition = None if runs else self.optional(step.get("if"))
        if "uses" in step:
            inputs = self.substituted(step.get("with"))
            uses = str(step["uses"]).strip()
            yield ActionStep(origin=origin, job=self.identity, uses=uses, inputs=inputs, condition=condition)
            if (local := _local_action(uses)) is not None:
                yield from self.composite_facts(origin, local, inputs, known, (*via, origin))
        if isinstance(run := step.get("run"), str):
            yield from self.run_facts(origin, step, self.substitute(run), known, condition, via)

    def run_facts(
        self,
        origin: Origin,
        step: Mapping[str, object],
        script: str,
        known: Known,
        condition: str | None,
        via: tuple[Origin, ...],
    ) -> Iterator[Fact]:
        """The commands of a step's script: split as its shell would, or, under a custom shell (`shell: Rscript {0}`),
        the one command of that program given the script, with the script's text where its file would be."""
        at, env = Origin(path=origin.path, at=(*origin.at, "run")), {**known.env, **self.substituted(step.get("env"))}
        directory = self.optional(step.get("working-directory")) or self.working_directory
        yield from _computed_directory(at, directory)
        if (custom := custom_shell(self.optional(step.get("shell")) or self.shell)) is not None:
            argv = tuple(script if word == "{0}" else word for word in custom)
            command = Command(origin=at, job=self.identity, argv=argv, line=script, env=env, directory=directory)
            yield replace(command, condition=condition, via=via)
            return
        yield from script_facts(
            script,
            job=self.identity,
            origin=at,
            env=env,
            directory=directory,
            condition=condition,
            opaque=EXPRESSION,
            via=via,
            powershell=self.powershell(step, known),
        )

    def powershell(self, step: Mapping[str, object], known: Known) -> bool:
        """Whether a step's script is PowerShell: its `shell`, the job's default, or the runner's (pwsh on Windows)."""
        shell = step.get("shell") or self.shell
        if shell is None:
            return known.os == "windows"
        return str(shell).split()[0] in ("pwsh", "powershell")

    def composite_facts(
        self, origin: Origin, directory: str, inputs: Mapping[str, str], known: Known, via: tuple[Origin, ...]
    ) -> Iterator[Fact]:
        """The steps of the local action in `directory`, when it is a composite action, with its inputs in place."""
        found = self._action(directory)
        if found is None:
            yield Unknown(
                origin=origin,
                subject=f"the action ./{directory}",
                reason="its action.yml is not read",
                hides="commands",
            )
            return
        path, action = found
        runs = action.get("runs")
        steps = runs.get("steps") if isinstance(runs, Mapping) and runs.get("using") == "composite" else None
        if not isinstance(steps, list) or len(via) > _CALL_DEPTH:
            return  # a JavaScript or Docker action, whose commands are its own code
        values = {**_input_defaults(action.get("inputs")), **inputs}
        for number, step in enumerate(steps):
            if isinstance(step, Mapping):
                at = Origin(path=path, at=("runs", "steps", number))
                yield from self.step_facts(at, _with_inputs(step, values), known, via)

    def _action(self, directory: str) -> tuple[str, Mapping[str, object]] | None:
        for name in ("action.yml", "action.yaml"):
            # `uses: ./` is the repository's own action, at its root.
            path = f"{directory}/{name}" if directory else name
            if self.load is not None and isinstance(document := self.load(path), Mapping):
                return path, document
        return None


_INPUT = re.compile(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}")


def _local_action(uses: str) -> str | None:
    """The directory of an action in the same repository (`./.github/actions/build`), else None."""
    path = _local(uses)
    return None if path is None else path.rstrip("/")


def _input_defaults(inputs: object) -> dict[str, str]:
    if not isinstance(inputs, Mapping):
        return {}
    found = ((name, spec.get("default")) for name, spec in inputs.items() if isinstance(spec, Mapping))
    return {
        str(name): str(default).lower() if isinstance(default, bool) else str(default)
        for name, default in found
        if default is not None
    }


def _with_inputs[T](value: T, inputs: Mapping[str, str]) -> T:
    """`value` (a step, or part of one) with each `${{ inputs.<name> }}` replaced by the input's value ("" when it has
    none)."""
    if isinstance(value, str):
        return _INPUT.sub(lambda match: inputs.get(match[1], ""), value)  # type: ignore[return-value]
    if isinstance(value, Mapping):
        return {key: _with_inputs(item, inputs) for key, item in value.items()}  # type: ignore[return-value]
    if isinstance(value, list):
        return [_with_inputs(item, inputs) for item in value]  # type: ignore[return-value]
    return value


# GitHub runs at most this many levels of reusable workflows.
_CALL_DEPTH = 4


def _only_called(document: Mapping[object, object]) -> bool:
    """Whether a workflow runs only when another calls it (`on: workflow_call`)."""
    triggers = document.get("on", document.get(True))  # YAML 1.1 reads a bare `on` as true
    names = [triggers] if isinstance(triggers, str) else list(triggers) if isinstance(triggers, (list, Mapping)) else []
    return names == ["workflow_call"]


def _computed_directory(origin: Origin, directory: str | None) -> Iterator[Unknown]:
    """A working directory computed by an expression (`packages/${{ matrix.package }}` of a computed matrix): where the
    commands run, and so what they cover, is not known."""
    if directory is not None and "${{" in directory:
        subject = f"the working directory {directory}"
        yield Unknown(origin=origin, subject=subject, reason="it is computed by an expression", hides="commands")


def _run_defaults(scope: Mapping[str, object]) -> dict[str, object]:
    defaults = scope.get("defaults")
    run = defaults.get("run") if isinstance(defaults, Mapping) else None
    return dict(run) if isinstance(run, Mapping) else {}


def _local(uses: object) -> str | None:
    """The path of a reusable workflow or action in the same repository (`./.github/workflows/build.yml`,
    `$/.github/actions/build`), else None."""
    text = str(uses)
    for prefix in ("./", "$/"):
        if text.startswith(prefix) and "@" not in text:
            return text.removeprefix(prefix)
    return None


def workflow_facts(path: str, document: object, load: Load | None = None, caller: str = "") -> Iterator[Fact]:
    """The jobs of a workflow, one per matrix combination, with the commands and actions each one runs. A job that
    calls a reusable workflow of the same repository runs that workflow's jobs (read with `load`); one in another
    repository is unknown."""
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return
    if not caller and _only_called(document):
        return  # its jobs run where another workflow calls it
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        if "uses" not in job:
            yield from _job_facts(path, str(job_id), job, document, caller, load)
            continue
        uses = str(job["uses"]).strip()
        called = _local(uses) or _own(uses, load)
        within_depth = caller.count(" → ") < _CALL_DEPTH
        if called is not None and load is not None and within_depth and (target := load(called)) is not None:
            yield from workflow_facts(called, target, load, f"{caller}{path}:{job_id} → ")
            continue
        yield Unknown(
            origin=Origin(path=path, at=("jobs", str(job_id))),
            subject=f"job {job_id}",
            reason=f"it calls the reusable workflow {uses}, which is not read",
            hides="jobs",
        )


def _own(uses: object, load: Load | None) -> str | None:
    """The path of a reusable workflow of this repository referenced by its full name
    (`apple/swift-nio/.github/workflows/unit_tests.yml@main` in swift-nio's own checkout), else None."""
    text, _, _ref = str(uses).partition("@")
    owner, _, rest = text.partition("/")
    name, _, path = rest.partition("/")
    repository = load(REPOSITORY) if load is not None and path else None
    return path if isinstance(repository, str) and repository.lower() == f"{owner}/{name}".lower() else None


def _uses(entries: object) -> list[str]:
    if not isinstance(entries, list):
        return []
    return [str(entry["uses"]).strip() for entry in entries if isinstance(entry, Mapping) and "uses" in entry]


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
            r"/actions/workflows/[^/\s]+/badge\.svg|/workflows/[^/\s]+/badge\.svg|img\.shields\.io/github/actions/workflow/status/"
            r"|badgen\.net/github/(?:checks|status)/",
        ),
    ),
    step_references=action_references,
    facts=workflow_facts,
)
