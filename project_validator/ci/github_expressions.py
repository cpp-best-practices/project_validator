"""Evaluating the GitHub Actions expressions of `if:` conditions, as far as a checkout shows their values.

`runner.os`, `matrix.*` and the workflow's and job's `env.*` are known; everything else (`github.*`, `secrets.*`,
`steps.*`, `needs.*`, unknown functions) is not, and makes the result unknown (None) unless the rest decides it:
`false && x` is false and `true || x` is true whatever `x` is. `&&` and `||` yield the operand that decides them, as
GitHub's do, so `${{ matrix.asan && '-fsanitize=address' || '' }}` renders its branch. Comparisons ignore case, as
GitHub's do. A step's status functions are judged for a run in which every step succeeds.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import reduce

from project_validator.ci.github_expression_syntax import (
    Call,
    Comparison,
    ExpressionSyntaxError,
    Literal,
    Logical,
    Node,
    Not,
    Reference,
    Value,
    parse,
)

_UNKNOWN = object()
# A value that is not known whose truth is: `x || 'a'` with `x` unknown is `x` or 'a', truthy either way. It decides
# a condition, but renders, compares and is passed to a function as unknown.
_SOME_TRUTHY, _SOME_FALSY = object(), object()
_UNSEEN = (_UNKNOWN, _SOME_TRUTHY, _SOME_FALSY)
type Maybe = Value | object  # a Value, _UNKNOWN, _SOME_TRUTHY or _SOME_FALSY

_RUNNER_OS = {"linux": "Linux", "windows": "Windows", "macos": "macOS"}
_STATUS = {"success": True, "always": True, "failure": False, "cancelled": False}


@dataclass(frozen=True, slots=True, kw_only=True)
class Known:
    """What a checkout shows about one job: its OS, its matrix combination and its environment."""

    os: str
    matrix: Mapping[str, object]
    env: Mapping[str, str]
    # Whether `matrix` is the combination's values; a matrix computed by an expression has values that are not seen.
    matrix_known: bool = True
    # A called workflow's inputs: what its caller passes in `with:`, or the declared defaults.
    inputs: Mapping[str, str] = field(default_factory=dict)


def _text(value: Maybe) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # As JavaScript writes a number: a whole one without a fraction or an exponent (below 1e21, where it would).
        return str(int(value)) if value.is_integer() and abs(value) < 1e21 else repr(value)
    return str(value)


def _truthy(value: Maybe) -> Maybe:
    if value is _UNKNOWN or value is _SOME_TRUTHY or value is _SOME_FALSY:
        return _UNKNOWN if value is _UNKNOWN else value is _SOME_TRUTHY
    return value not in (None, False, 0.0, "")


class _Evaluator:
    """Walks an expression's tree (`github_expression_syntax`) with what the checkout shows about one job."""

    def __init__(self, known: Known) -> None:
        self.known = known

    def value(self, node: Node) -> Maybe:
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, Reference):
            return self.reference(node.name)
        if isinstance(node, Not):
            truth = _truthy(self.value(node.operand))
            return _UNKNOWN if truth is _UNKNOWN else not truth
        if isinstance(node, Comparison):
            if node.operator not in ("==", "!="):
                return _UNKNOWN  # ordering is not evaluated
            return _compare(node.operator, self.value(node.left), self.value(node.right))
        if isinstance(node, Logical):
            combine = _either if node.operator == "||" else _both
            return reduce(
                lambda left, right: combine(node.operator, left, self.value(right)),
                node.operands[1:],
                self.value(node.operands[0]),
            )
        if isinstance(node, Call):
            return _function(node.name.lower(), [self.value(argument) for argument in node.arguments])
        return _UNKNOWN  # an index is not evaluated

    def reference(self, name: str) -> Maybe:
        head, _, rest = name.partition(".")
        if name == "runner.os":
            return _RUNNER_OS.get(self.known.os, _UNKNOWN)
        if head == "matrix":
            return _lookup(self.known.matrix, rest) if self.known.matrix_known else _UNKNOWN
        if head == "env" and rest in self.known.env:
            return self.known.env[rest]
        if head == "inputs" and rest in self.known.inputs:
            return self.known.inputs[rest]
        return _UNKNOWN


type _Combine = Callable[[str, Maybe, Maybe], Maybe]


def _lookup(values: Mapping[str, object], dotted: str) -> Maybe:
    value: object = values
    for key in dotted.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, (str, float, bool)) or value is None else str(value)


def _either(_: str, left: Maybe, right: Maybe) -> Maybe:
    """`a || b` as GitHub evaluates it: `a` when it is truthy, else `b` (the operand itself, not a boolean: a ternary
    renders its branch). When `a` is unknown only a truthy `b` decides it, and only its truth: `a` or `b`."""
    truth = _truthy(left)
    if truth is _UNKNOWN:
        return _SOME_TRUTHY if _truthy(right) is True else _UNKNOWN
    return left if truth else right


def _both(_: str, left: Maybe, right: Maybe) -> Maybe:
    """`a && b` as GitHub evaluates it: `a` when it is falsy, else `b`. When `a` is unknown only a falsy `b` decides
    it, and only its truth: `a` or `b`."""
    truth = _truthy(left)
    if truth is _UNKNOWN:
        return _SOME_FALSY if _truthy(right) is False else _UNKNOWN
    return right if truth else left


def _compare(operator: str, left: Maybe, right: Maybe) -> Maybe:
    if left in _UNSEEN or right in _UNSEEN or isinstance(left, _Structured) or isinstance(right, _Structured):
        return _UNKNOWN
    equal = _text(left).lower() == _text(right).lower()
    return equal if operator == "==" else not equal


class _Structured(str):
    """A JSON list or object `fromJSON` read, as its text: it renders as that text (a runner's labels), but what it
    holds is not compared or searched as text (`contains(fromJSON('[1]'), 1)` asks about its elements)."""


def _from_json(text: str) -> Maybe:
    """`fromJSON(text)`: a JSON scalar as its value; a list or an object kept as its text, for what it names (a runner's
    labels); unknown when the text is not JSON."""
    try:
        value = json.loads(text)
    except ValueError:
        return _UNKNOWN
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value if isinstance(value, (str, float, bool)) or value is None else _Structured(text)


def _opaque(value: Maybe) -> bool:
    """Whether a value's text is not what a test of text can ask about: not known, or a JSON list or object."""
    return value in _UNSEEN or isinstance(value, _Structured)


def _function(name: str, arguments: list[Maybe]) -> Maybe:
    if name in _STATUS and not arguments:
        return _STATUS[name]
    if name == "fromjson" and len(arguments) == 1:
        return _UNKNOWN if arguments[0] in _UNSEEN else _from_json(_text(arguments[0]))
    tests: dict[str, Callable[[str, str], bool]] = {
        "contains": lambda text, part: part in text,
        "startswith": str.startswith,
        "endswith": str.endswith,
    }
    if name not in tests or len(arguments) != 2 or any(_opaque(argument) for argument in arguments):
        return _UNKNOWN
    text, part = (_text(argument).lower() for argument in arguments)
    return tests[name](text, part)


def _parsed(expression: str, known: Known) -> Maybe:
    try:
        tree = parse(expression)
    except ExpressionSyntaxError:
        return _UNKNOWN
    return _Evaluator(known).value(tree)


def evaluate(condition: str, known: Known) -> bool | None:
    """Whether a job or step with `condition` runs, or None when the checkout does not show it."""
    value = _truthy(_parsed(condition, known))
    return None if value is _UNKNOWN else bool(value)


def rendered(expression: str, known: Known) -> str | None:
    """The text GitHub puts in place of `${{ expression }}`, or None when the checkout does not show it."""
    value = _parsed(expression, known)
    return None if value in _UNSEEN else _text(value)
