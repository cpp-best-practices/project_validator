"""pre-commit (and prek, which reads the same configuration): the hooks `pre-commit run` runs.

A local hook (`repo: local`) runs its `entry` with its `args`. A hook from another repository runs an entry defined
in that repository, which is not read; it is recorded by its id, which by convention names its tool (`ruff`,
`clang-format`), with its args.
"""

from collections.abc import Iterator, Mapping

from project_validator import yaml_support
from project_validator.core import Context
from project_validator.evidence import PRE_COMMIT_CONFIGURATION
from project_validator.facts import Command, Origin, Unknown
from project_validator.facts.arguments import positional
from project_validator.facts.expansion import CommandExpander, Expansion, Invocation, Script, found_at

_PROGRAMS = frozenset({"pre-commit", "prek"})
# The stages `pre-commit run` runs when no --hook-stage is given; hooks without `stages` run in every stage.
_DEFAULT_STAGES = frozenset({"pre-commit", "commit"})


def _hooks(document: object) -> Iterator[tuple[int, int, str, Mapping[str, object]]]:
    """(repo index, hook index, repo, hook) for each hook in a configuration document."""
    repos = document.get("repos") if isinstance(document, Mapping) else None
    for repo_index, repo in enumerate(repos if isinstance(repos, list) else []):
        hooks = repo.get("hooks") if isinstance(repo, Mapping) else None
        for hook_index, hook in enumerate(hooks if isinstance(hooks, list) else []):
            if isinstance(hook, Mapping) and isinstance(hook.get("id"), str):
                yield repo_index, hook_index, str(repo.get("repo", "")), hook


def _runs_in(hook: Mapping[str, object], stage: str | None) -> bool:
    stages = hook.get("stages")
    if not isinstance(stages, list):
        return True
    return bool({str(found) for found in stages} & ({stage} if stage else _DEFAULT_STAGES))


def _expansion(path: str, at: tuple[str | int, ...], repo: str, hook: Mapping[str, object]) -> Expansion:
    origin = Origin(path=path, at=at)
    args = hook.get("args")
    words = tuple(str(arg) for arg in args) if isinstance(args, list) else ()
    if repo == "local" and isinstance(entry := hook.get("entry"), str):
        return Script(text=" ".join((entry, *(f"'{word}'" for word in words))), origin=origin)
    return Invocation(argv=(str(hook["id"]), *words), line=f"the {hook['id']} hook of {repo}", origin=origin)


_OPTIONS = frozenset({"--hook-stage", "--config", "-c", "--files", "--from-ref"})


def _configuration(command: Command, context: Context, options: dict[str, str]) -> tuple[str, object] | Unknown:
    """The parsed configuration `pre-commit run` reads, or why it cannot be read."""
    named = options.get("--config") or options.get("-c")
    path = found_at(context, command.directory, [named] if named else PRE_COMMIT_CONFIGURATION)
    if path is None:
        return Unknown(origin=command.origin, subject="the hooks", reason="no pre-commit configuration is found")
    try:
        return path, yaml_support.load(context.project.read_text(path))
    except yaml_support.YamlError as error:
        return Unknown(origin=command.origin, subject="the hooks", reason=f"{path} does not parse ({error})")


def _pre_commit_hooks(command: Command, context: Context) -> Iterator[Expansion] | None:
    """`pre-commit run`, `pre-commit run ruff --all-files`: the configured hooks it runs."""
    if command.argv[:2] not in {(program, "run") for program in _PROGRAMS}:
        return None
    words, options = positional(command.argv[1:], _OPTIONS)
    found = _configuration(command, context, options)
    if isinstance(found, Unknown):
        return iter((found,))
    path, document = found
    stage = options.get("--hook-stage")
    return (
        _expansion(path, ("repos", repo_index, "hooks", hook_index), repo, hook)
        for repo_index, hook_index, repo, hook in _hooks(document)
        if (not words or hook["id"] in words) and _runs_in(hook, stage)
    )


PRE_COMMIT_HOOKS = CommandExpander(name="pre-commit hooks", expand=_pre_commit_hooks)
