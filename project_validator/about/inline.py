"""Inline comments: the comments in the product's code that turn rules off, for each tool CI runs (and the
compiler's), counted by whether the rules they turn off find bugs (upstream #295). Those that turn off only lint rules
that find no bugs cost a tool's strength nothing, so this is where they show; those that find bugs are counted beside
them, as the score weighs them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from project_validator.about.detail import Detail
from project_validator.facts import Facts
from project_validator.facts.suppressions import Suppressions, finding_bugs
from project_validator.facts.tools import ToolRun

# The tool whose comments count without CI naming it: every C and C++ build runs a compiler.
_ALWAYS = frozenset({"compiler"})


def _rules(counted: Counter[str]) -> str:
    """`E501 2 times, N802, every rule`."""
    return ", ".join(
        f"{'every rule' if rule == '*' else rule}{f' {count} times' if count > 1 else ''}"
        for rule, count in counted.most_common()
    )


@dataclass
class _Tally:
    """Comments of one kind, and how often each rule is named in them."""

    comments: int = 0
    rules: Counter[str] = field(default_factory=Counter)

    def add(self, rules: tuple[str, ...]) -> None:
        self.comments += 1
        self.rules.update(rules)

    def said(self, what: str) -> list[str]:
        """`3 turn off lint rules that find no bugs (E501 2 times, N802)`, or nothing."""
        if not self.comments:
            return []
        return [f"{self.comments} {'turns' if self.comments == 1 else 'turn'} off {what} ({_rules(self.rules)})"]


def _counted(facts: Facts) -> dict[str, tuple[_Tally, _Tally]]:
    """For each tool CI runs, its comments that turn off only lint rules that find no bugs, and those that don't."""
    running = {run.tool for run in facts.of(ToolRun)} | _ALWAYS
    found: dict[str, tuple[_Tally, _Tally]] = {}
    for suppressions in facts.of(Suppressions):
        if suppressions.tool in running and suppressions.found:
            lint, bugs = found.setdefault(suppressions.tool, (_Tally(), _Tally()))
            for each in suppressions.found:
                finding = finding_bugs(suppressions.tool, each.rules)
                if finding:
                    bugs.add(finding)
                else:
                    lint.add(each.rules)
    return found


def inline_comments(facts: Facts) -> Iterator[Detail]:
    """`ruff check: 3 turn off lint rules that find no bugs (E501 2 times, N802); 1 turns off rules that find bugs
    (F401)`."""
    found = sorted(_counted(facts).items())
    if not found:
        return
    clauses = [
        f"{tool}: {'; '.join(lint.said('lint rules that find no bugs') + bugs.said('rules that find bugs'))}"
        for tool, (lint, bugs) in found
    ]
    data = {tool: {"lint": dict(lint.rules), "bugs": dict(bugs.rules)} for tool, (lint, bugs) in found}
    yield Detail(group="Tools", subject="inline comments", text="; ".join(clauses), data={"tools": data})


__all__ = ["inline_comments"]
