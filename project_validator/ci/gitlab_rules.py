"""Whether a GitLab job runs, by its `rules:` (or `only:`/`except:`), as far as the pipeline shows (upstream #361).

A rule's `if:` is evaluated with the variables the pipeline sets. GitLab's own predefined variables (`CI_*`,
`GITLAB_*`) say which run it is (the branch, the tag, the pipeline's source), and so do `changes:` and `exists:`: a
condition on them holds in the runs CI makes it hold in. Any other variable the pipeline does not set may be set by
the project's settings, which the checkout does not show: a condition on one is required. The first rule that
matches decides, by its `when:` (`never`: the job does not run; `manual`: someone has to start it).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

# A job that runs, in the runs CI makes.
RUNS = True
# What a manual job requires.
MANUAL = "someone starts it"


class _Kind:
    """A value that is not known: one the run decides (`RUN`), or one the checkout does not show (`REQUIRED`)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


_RUN, _REQUIRED = _Kind("RUN"), _Kind("REQUIRED")
type _Truth = bool | _Kind
type _Value = str | _Kind | None

_PREDEFINED = re.compile(r"(?:CI|GITLAB)_\w+|CI")
_TOKEN = re.compile(
    r"\s*(?:(?P<variable>\$\{?\w+\}?)|(?P<string>\"[^\"]*\"|'[^']*')|(?P<regex>/(?:\\.|[^/\\])*/[a-z]*)"
    r"|(?P<operator>==|!=|=~|!~|&&|\|\||\(|\))|(?P<null>null\b))"
)


class _NotRead(Exception):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    at = 0
    while at < len(text.rstrip()):
        match = _TOKEN.match(text, at)
        if match is None:
            raise _NotRead(text)
        kind = str(match.lastgroup)
        found.append((kind, match[kind]))
        at = match.end()
    return found


def _either(left: _Truth, right: _Truth) -> _Truth:
    if left is True or right is True:
        return True
    if left is False or right is False:
        return right if left is False else left
    return _RUN if _RUN in (left, right) else _REQUIRED


def _both(left: _Truth, right: _Truth) -> _Truth:
    if left is False or right is False:
        return False
    if left is True or right is True:
        return right if left is True else left
    return _REQUIRED if _REQUIRED in (left, right) else _RUN


class _Expression:
    """A rule's `if:`, parsed and evaluated at once: `||` binds looser than `&&`, comparisons tighter."""

    def __init__(self, text: str, variables: Mapping[str, str]) -> None:
        self.tokens = _tokens(text)
        self.variables = variables
        self.at = 0

    def evaluate(self) -> _Truth:
        value = self.either()
        if self.at != len(self.tokens):
            raise _NotRead
        return value

    def next(self, *operators: str) -> bool:
        if self.at < len(self.tokens) and self.tokens[self.at][1] in operators:
            self.at += 1
            return True
        return False

    def either(self) -> _Truth:
        return self.joined(self.both, "||", _either)

    def both(self) -> _Truth:
        return self.joined(self.comparison, "&&", _both)

    def joined(self, operand: Callable[[], _Truth], operator: str, join: Callable[[_Truth, _Truth], _Truth]) -> _Truth:
        value = operand()
        while self.next(operator):
            value = join(value, operand())
        return value

    def comparison(self) -> _Truth:
        if self.next("("):
            value = self.either()
            if not self.next(")"):
                raise _NotRead
            return value
        left = self.operand()
        for operator in ("==", "!=", "=~", "!~"):
            if self.next(operator):
                return _compared(operator, left, self.operand())
        return left if isinstance(left, _Kind) else bool(left)

    def operand(self) -> _Value:
        if self.at >= len(self.tokens):
            raise _NotRead
        kind, text = self.tokens[self.at]
        self.at += 1
        if kind == "variable":
            name = text.strip("${}")
            if name in self.variables:
                return self.variables[name]
            return _RUN if _PREDEFINED.fullmatch(name) else _REQUIRED
        if kind == "string":
            return text[1:-1]
        if kind in ("regex", "null"):
            return None if kind == "null" else text
        raise _NotRead


def _compared(operator: str, left: _Value, right: _Value) -> _Truth:
    if isinstance(left, _Kind):
        return left
    if isinstance(right, _Kind):
        return right
    if operator in ("=~", "!~"):
        if right is None or not right.startswith("/"):
            raise _NotRead
        pattern, _, flags = right[1:].rpartition("/")
        found = re.search(pattern, left or "", re.IGNORECASE if "i" in flags else 0) is not None
        return found if operator == "=~" else not found
    return (left == right) if operator == "==" else (left != right)


def _truth(text: str, variables: Mapping[str, str]) -> _Truth:
    try:
        return _Expression(text, variables).evaluate()
    except (_NotRead, re.error):
        return _REQUIRED


type Outcome = bool | str


def _when(when: object) -> Outcome:
    return False if when == "never" else MANUAL if when == "manual" else RUNS


def _rules(rules: list[object], variables: Mapping[str, str]) -> Outcome:
    """The first rule that matches decides; a rule on the run lets the runs it does not hold in go on to the next."""
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            continue
        written = rule.get("if")
        truth: _Truth = True if written is None else _truth(str(written), variables)
        if "changes" in rule or "exists" in rule:
            truth = _both(truth, _RUN)
        when = rule.get("when", "on_success")
        if truth is False or (truth is _RUN and when == "never"):
            continue
        if truth is True or truth is _RUN:
            return _when(when)
        if when != "never":
            return str(written)
        rest = _rules(rules[index + 1 :], variables)
        return rest if rest is False else f"not ({written})" + ("" if rest is True else f" and {rest}")
    return False


def _variables_truth(expressions: object, variables: Mapping[str, str]) -> tuple[_Truth, str]:
    written = [found for found in expressions if isinstance(found, str)] if isinstance(expressions, list) else []
    truth: _Truth = False
    for expression in written:
        truth = _either(truth, _truth(expression, variables))
    return truth, " or ".join(written)


def _only_except(job: Mapping[str, object], variables: Mapping[str, str]) -> Outcome:
    """`only:` and `except:`: their refs and changes say which runs; their variables are settled as rules' are."""
    outcome: Outcome = RUNS
    for key in ("only", "except"):
        found = job.get(key)
        if found is None:
            continue
        if not isinstance(found, Mapping) or "variables" not in found:
            continue  # refs, changes: some runs
        truth, written = _variables_truth(found["variables"], variables)
        if key == "except":
            truth, written = (not truth if isinstance(truth, bool) else truth), f"not ({written})"
        if truth is False:
            return False
        if truth is _REQUIRED:
            outcome = written if outcome is RUNS else f"{outcome} and {written}"
    return outcome


def job_requirement(job: Mapping[str, object], variables: Mapping[str, str]) -> Outcome:
    """Whether a job runs: `RUNS` (in the runs CI makes), False (never), or what it requires, as written."""
    rules = job.get("rules")
    if isinstance(rules, list):
        return _rules(rules, variables)
    if job.get("when") in ("never", "manual"):
        return _when(job.get("when"))
    return _only_except(job, variables)


__all__ = ["MANUAL", "RUNS", "Outcome", "job_requirement"]
