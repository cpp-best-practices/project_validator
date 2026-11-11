"""The static analysis and type checking aspects of tools (see `project_validator.facts.tools`).

An analyzer's run provides `analysis`; how much it finds depends on the checks the project defines for it (a
`.clang-tidy`), which is its `Definition`. A type checker's run provides `type-check` at `checks`, or also at `strict`
when it runs in its strict mode. Analyzers and type checkers are ordinary `Tool`s; `analyzer`, `analysed`,
`type_checker` and `type_checked` only spell them.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Definition, Run, Tool, defined_by, provided

ANALYSIS = "analysis"
TYPE_CHECK = "type-check"
# The one level of analysis: the run checks the code.
CHECKS = "checks"


class Strictness(enum.StrEnum):
    """`checks`: the type checker runs. `strict`: in its strict mode."""

    CHECKS = CHECKS
    STRICT = "strict"


def analyzer(
    *,
    name: str,
    languages: frozenset[str],
    how: str,
    analyses: Claim,
    rules: Definition | None = None,
    reads: tuple[str, ...] = (),
    required: bool = False,
) -> Tool:
    """A static analyzer: `how` to run it, and `rules`, where the project defines its checks (a tool without a
    default worth running needs them). A `required` analyzer finds what the others do not, so it must run too."""
    return Tool(
        name=name,
        languages=languages,
        can={ANALYSIS: {CHECKS: how}},
        claims=analyses,
        reads=reads,
        definitions={ANALYSIS: rules or defined_by()},
        required=frozenset({ANALYSIS}) if required else frozenset(),
    )


def analysed(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(ANALYSIS, CHECKS, read=read, heuristic=heuristic)


def type_checker(
    *,
    name: str,
    languages: frozenset[str],
    can: Mapping[Strictness, str],
    checks: Claim,
    configuration: Definition | None = None,
    reads: tuple[str, ...] = (),
) -> Tool:
    """A type checker: `can` maps each strictness to how to ask for it; `configuration`, where the project configures
    it."""
    return Tool(
        name=name,
        languages=languages,
        can={TYPE_CHECK: {str(level): how for level, how in can.items()}},
        claims=checks,
        reads=reads,
        definitions={TYPE_CHECK: configuration or defined_by()},
    )


def type_checked(*, strict: bool, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(
        TYPE_CHECK, Strictness.CHECKS, Strictness.STRICT if strict else None, read=read, heuristic=heuristic
    )


__all__ = [
    "ANALYSIS",
    "CHECKS",
    "TYPE_CHECK",
    "Strictness",
    "analysed",
    "analyzer",
    "type_checked",
    "type_checker",
]
