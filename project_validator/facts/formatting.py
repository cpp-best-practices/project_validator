"""The format aspect of tools (see `project_validator.facts.tools`): whether a run enforces the project's formatting.

A formatter run either checks the formatting, failing when a file is not formatted (`ruff format --check`,
`clang-format --dry-run -Werror`), or applies it, rewriting files (`black .`, `clang-format -i`). Applying it enforces
it too where what changed fails the job or is committed: pre-commit fails when a hook changes a file, a job may
fail on `git diff --exit-code`, or commit the changes back. Formatters are ordinary `Tool`s whose `can` holds a
`format` aspect; `format_tool` and `formatted` only spell them.
"""

import enum
from collections.abc import Iterable, Mapping

from project_validator.facts import ActionStep, Command, Facts, Setting, resolved
from project_validator.facts.arguments import has_option, program, starts_with
from project_validator.facts.expansion import from_hook
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

FORMAT = "format"


class Enforcement(enum.StrEnum):
    """`check`: the run fails when a file is not formatted. `apply`: it rewrites the files."""

    CHECK = "check"
    APPLY = "apply"


def format_tool(
    *,
    name: str,
    languages: frozenset[str],
    can: Mapping[Enforcement, str],
    formats: Claim,
    style: Definition,
    reads: tuple[str, ...] = (),
) -> Tool:
    """A formatter: `can` maps each way it runs to how to ask for it, and `style` says where the project defines its
    formatting (and whether it has a default style)."""
    return Tool(
        name=name,
        languages=languages,
        can={FORMAT: {str(level): how for level, how in can.items()}},
        claims=formats,
        reads=reads,
        definitions={FORMAT: style},
    )


# Steps that commit what a job changed back to the repository.
_COMMITTING_ACTIONS = frozenset(
    {"stefanzweifel/git-auto-commit-action", "peter-evans/create-pull-request", "endbug/add-and-commit"}
)


def _keeps(command: Command) -> bool | None:
    """Whether `command` fails when a file changed (`git diff --exit-code` or `--quiet`) or keeps the changes
    (`git commit`): True; whether it shows them for a later step to fail on (`git diff`, `git status --porcelain`):
    False; None when it does neither."""
    argv = resolved(command)
    if program(argv) != "git" or len(argv) < 2:
        return None
    if argv[1] == "commit" or (argv[1] == "diff" and has_option(argv, "--exit-code", "--quiet")):
        return True
    return False if argv[1] == "diff" or (argv[1] == "status" and has_option(argv, "--porcelain", "-s")) else None


def changes_enforced(command: Command, facts: Facts) -> bool | None:
    """Whether what `command` changes fails CI or is committed: it runs as a pre-commit hook (which fails when a hook
    changes a file), or its job checks the diff or commits it (True). Where the job does so is not told apart. A job
    that only shows the diff (`DIFF=$(git diff)`), for a later step to fail on, is taken to: False. None when nothing
    shows the changes."""
    if from_hook(command):
        return True
    steps = facts.where(ActionStep, job=command.job)
    if any(step.uses.partition("@")[0].lower() in _COMMITTING_ACTIONS for step in steps):
        return True
    kept = [found for other in facts.where(Command, job=command.job) if (found := _keeps(other)) is not None]
    return any(kept) if kept else None


def formatted(
    command: Command,
    facts: Facts,
    *,
    checks: bool,
    applies: bool = True,
    read: Iterable[Setting | str] = (),
    heuristic: bool = False,
) -> Run | None:
    """A formatter run: it enforces the formatting when it `checks` it, or `applies` it where the changes are
    enforced (see `changes_enforced`). A pre-commit hook applies it. A run that does neither (one that only prints the
    formatted code) is not a formatter run."""
    if not (checks or applies or from_hook(command)):
        return None
    enforced = None if checks else changes_enforced(command, facts)
    level = Enforcement.CHECK if checks or enforced is not None else Enforcement.APPLY
    return provided(FORMAT, level, read=read, heuristic=heuristic or enforced is False)


def _given(argv: tuple[str, ...], words: frozenset[str]) -> bool:
    return any(has_option(argv, word) if word.startswith("-") else word in argv[1:] for word in words)


def flagged(
    *prefixes: tuple[str, ...], checks: Iterable[str] | None = None, applies: Iterable[str] | None = None
) -> Claim:
    """The runs of a formatter by a command that starts with one of `prefixes` (`("ruff", "format")`): it checks when
    one of `checks` is given (when None: whenever it does not apply), and applies when one of `applies` is given
    (when None: whenever it does not check). A word starting with `-` is an option; another is a subcommand or
    argument anywhere after the prefix (`php-cs-fixer check`)."""
    checking = None if checks is None else frozenset(checks)
    applying = None if applies is None else frozenset(applies)

    def claims(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if starts_with(argv, *prefixes) is None:
            return None
        applied = applying is not None and _given(argv, applying)
        checked = not applied if checking is None else _given(argv, checking)
        return formatted(command, facts, checks=checked, applies=applied if applying is not None else not checked)

    return claims


__all__ = ["FORMAT", "Enforcement", "changes_enforced", "flagged", "format_tool", "formatted"]
