"""The function length aspect of tools (see `project_validator.facts.tools`): a run limits how long functions may be,
with a measuring tool told a limit (lizard) or with a linter's rule (clang-tidy's readability-function-size, RuboCop's
Metrics/MethodLength).

A linter limits function length only while its rule is on: some rules are on by default unless the project's settings
turn them off, others only once the settings turn them on. Limiters are ordinary `Tool`s; `limiter` only spells them.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from project_validator.facts import Command, Facts, Setting
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

FUNCTION_LENGTH = "function-length"
# `measures`: the run measures functions (a limiter whose limit is off, which fails on nothing). `limits`: it fails on
# a function longer than its limit.
MEASURES = "measures"
LIMITS = "limits"


def _none(_facts: Facts) -> Sequence[Setting]:
    return ()


def _never(_command: Command) -> bool:
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    """A linter's rule that limits function length: `enabled`, the settings that turn it on, and `disabled`, those
    that turn it off; `default`, whether it is on without either; `flagged`, whether a command turns it on itself
    (`phpmd src text codesize`). `describe` says how to turn it on."""

    describe: str
    enabled: Callable[[Facts], Sequence[Setting]] = _none
    disabled: Callable[[Facts], Sequence[Setting]] = _none
    default: bool = False
    flagged: Callable[[Command], bool] = _never


def limited(*, active: bool = True, read: Sequence[Setting | str] = (), heuristic: bool = False) -> Run:
    """A run that limits function length, or, not `active`, one that only measures it (a limiter without a limit)."""
    return provided(FUNCTION_LENGTH, MEASURES, LIMITS if active else None, read=read, heuristic=heuristic)


def limiter(
    *, name: str, languages: frozenset[str], how: str, runs: Claim, rule: Rule, reads: tuple[str, ...] = ()
) -> Tool:
    """A linter whose `rule` limits function length, run as the linter's own claim `runs` reads (any aspect): `how`
    to run it with the rule on."""

    def claims(command: Command, facts: Facts) -> Run | None:
        run = runs(command, facts)
        if run is None:
            return None
        on, off = rule.enabled(facts), rule.disabled(facts)
        active = rule.flagged(command) or bool(on) or (rule.default and not off)
        return limited(active=active, read=(*run.read, *(on or off)), heuristic=run.heuristic)

    definition = Definition(
        found=lambda facts: (setting.path for setting in rule.enabled(facts)),
        default=rule.default,
        describe=rule.describe,
    )
    return Tool(
        name=name,
        languages=languages,
        can={FUNCTION_LENGTH: {LIMITS: how}},
        claims=claims,
        reads=reads,
        definitions={FUNCTION_LENGTH: definition},
    )


__all__ = ["FUNCTION_LENGTH", "LIMITS", "MEASURES", "Rule", "limited", "limiter"]
