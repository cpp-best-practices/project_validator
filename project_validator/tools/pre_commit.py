"""pre-commit (and prek, which reads the same configuration): the hooks `pre-commit run` runs.

A local hook (`repo: local`) runs its `entry` with its `args`. A hook from another repository runs an entry defined
in that repository, which is not read; it is recorded by its id, which by convention names its tool (`ruff`,
`clang-format`), with its args.

devenv writes the configuration from the hooks `devenv.nix` enables (`git-hooks.hooks.rustfmt.enable = true;`, named
`pre-commit` before devenv 1.4) when its shell starts, and ignores the file it writes: where no configuration is
committed, those hooks are what `pre-commit run` runs, each by its id.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from project_validator import yaml_support
from project_validator.core import Context
from project_validator.evidence import DEVENV, DEVENV_HOOKS, PRE_COMMIT_CONFIGURATION
from project_validator.facts import Command, Fact, Origin, Setting, Unknown
from project_validator.facts.arguments import positional
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Invocation, Script, found_at
from project_validator.facts.nix_syntax import attributes
from project_validator.facts.settings import SettingsReader
from project_validator.facts.shell import split_words

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
    return _invocation(str(hook["id"]), words, repo, origin)


def _invocation(hook: str, words: tuple[str, ...], repo: str, origin: Origin) -> Invocation:
    program = _PROGRAMS_OF_HOOKS.get(hook, hook)
    return Invocation(argv=(program, *words), line=f"the {hook} hook of {repo}", origin=origin)


# Hooks whose id is not their program's name: the program the repository's hook runs (hadolint's `hadolint-docker`
# runs hadolint in its image).
_PROGRAMS_OF_HOOKS = {"hadolint-docker": "hadolint"}


_OPTIONS = frozenset(
    {"--hook-stage", "--config", "-c", "--files", "--from-ref", "--to-ref", "--source", "-s", "--origin", "-o"}
)


def _devenv_hooks(path: str, context: Context) -> dict[str, Origin]:
    """The ids of the hooks the `devenv.nix` at `path` enables, each where it does."""
    return {
        found[2]: Origin(path=path, at=found[:3])
        for found, value in attributes(context.project.read_text(path))
        if len(found) == 4 and found[0] in DEVENV_HOOKS and found[1] == "hooks" and found[3] == "enable"
        if value == "true"
    }


def _devenv_run(path: str, enabled: dict[str, Origin], words: list[str], skipped: set[str]) -> Iterator[Expansion]:
    """The hooks a `devenv.nix` enables that `pre-commit run` runs: those it names, if any, but those SKIP names."""
    for hook, origin in enabled.items():
        if (not words or hook in words) and hook not in skipped:
            yield _invocation(hook, (), path, origin)


def _configuration(command: Command, context: Context, options: dict[str, str]) -> tuple[str, object] | Unknown:
    """The parsed configuration `pre-commit run` reads (the hooks a `devenv.nix` enables, where none is committed),
    or why it cannot be read."""
    named = options.get("--config") or options.get("-c")
    path = found_at(context, command.directory, [named] if named else PRE_COMMIT_CONFIGURATION)
    if path is None and not named and (devenv := found_at(context, command.directory, [DEVENV])) is not None:
        return devenv, _devenv_hooks(devenv, context)
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
    # pre-commit skips the hooks its SKIP variable names.
    skipped = {name.strip() for name in command.env.get("SKIP", "").split(",")}
    if path.endswith(DEVENV) and isinstance(document, dict):
        return _devenv_run(path, document, words, skipped)
    return (
        _expansion(path, ("repos", repo_index, "hooks", hook_index), repo, hook)
        for repo_index, hook_index, repo, hook in _hooks(document)
        if (not words or hook["id"] in words) and _runs_in(hook, stage) and hook["id"] not in skipped
    )


PRE_COMMIT_HOOKS = CommandExpander(name="pre-commit hooks", expand=_pre_commit_hooks)
_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def _action_arguments(value: str) -> list[str]:
    """The words of an action's extra arguments, without the expressions in them: Bash-it's chooses the refs to check
    (`--from-ref …` or `--last-commit`), which select no hook."""
    return list(split_words(_EXPRESSION.sub(" ", value)))


# The pre-commit action runs every hook, or what its `extra_args` say.
PRE_COMMIT_ACTION = Action(
    name="pre-commit/action",
    runs=lambda inputs: (
        ("pre-commit", "run", "--show-diff-on-failure", *_action_arguments(inputs.get("extra_args", "--all-files"))),
    ),
)

# prek's action runs every hook the same way, with its own name for the arguments.
PREK_ACTION = Action(
    name="j178/prek-action",
    runs=lambda inputs: (
        ("prek", "run", "--show-diff-on-failure", *_action_arguments(inputs.get("extra-args", "--all-files"))),
    ),
)


def _read_hooks(path: str, text: str) -> Iterator[Fact]:
    """Each hook a pre-commit configuration defines, as its repository, id, entry and arguments: a hook runs before
    each commit wherever it is installed, whether or not CI runs it too."""
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        yield Unknown(origin=Origin(path=path), subject="the pre-commit hooks", reason=str(error), hides="settings")
        return
    for repo_index, hook_index, repo, hook in _hooks(document):
        args = hook.get("args")
        words = [str(hook["id"]), str(hook.get("entry", "")), *(map(str, args) if isinstance(args, list) else ())]
        origin = Origin(path=path, at=("repos", repo_index, "hooks", hook_index))
        yield Setting(origin=origin, tool="pre-commit", key="hook", value=" ".join((repo, *words)).strip())


PRE_COMMIT_SETTINGS = SettingsReader(name="pre-commit", files=PRE_COMMIT_CONFIGURATION, read=_read_hooks)
