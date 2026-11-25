"""Azure Pipelines template expressions (`${{ }}`), evaluated where a template is expanded, before the pipeline runs.

A template's `${{ parameters.x }}` (and `variables.x`, and an `each` loop's variable) take their values; the
conditional insertions `${{ if … }}`, `${{ elseif … }}` and `${{ else }}`, and the loop `${{ each x in … }}`, expand
the mapping or sequence they are keys of. The functions are Azure's: `eq`, `ne`, `not`, `and`, `or`, `in`, `notIn`,
`gt`, `ge`, `lt`, `le`, `length`, `format`, `coalesce`, `contains`, `startsWith`, `endsWith`, `lower`, `upper`,
`replace` and `join`; string comparisons ignore case. `${{ variables.name }}` is left as written where the scope
does not set it, for the reader to substitute the job's; a condition on a variable the pipeline sets as it runs
(`Build.Reason`) may hold, so its branch is inserted (see `_Insertions`). Anything else (another function, a value
known only as the pipeline runs, an `${{ insert }}`) is not evaluated: `Unevaluated` says what. Expressions are parsed
by the GitHub expression parser, whose syntax Azure's shares.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping

from project_validator.ci.github_expression_syntax import (
    Call,
    Comparison,
    ExpressionSyntaxError,
    Index,
    Literal,
    Node,
    Not,
    Reference,
    parse,
)


class Unevaluated(Exception):
    """An expression that cannot be evaluated where the template is expanded, and why."""


type Scope = Mapping[str, object]

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_DIRECTIVE = re.compile(r"^\$\{\{\s*(?P<kind>if|elseif|else|each|insert)\b(?P<rest>.*?)\}\}$", re.DOTALL)
_EACH = re.compile(r"^\s*(?P<name>\w+)\s+in\s+(?P<collection>.+?)\s*$", re.DOTALL)


def _parsed(expression: str) -> Node:
    try:
        return parse(expression)
    except ExpressionSyntaxError as error:
        raise Unevaluated(f"the expression {expression.strip()!r} does not parse") from error


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return "" if value is None else str(value)


def _truthy(value: object) -> bool:
    return value not in (None, False, 0, "") and not (isinstance(value, (list, Mapping)) and not value)


def _same(left: object, right: object) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    return left == right


def _number(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise Unevaluated(f"{value!r} is not a number") from error


def _format(template: object, *arguments: object) -> str:
    """Azure's `format`: `{0}` is the first argument; `{{` and `}}` are braces."""
    text = _text(template).replace("{{", "\0").replace("}}", "\1")
    filled = re.sub(r"\{(\d+)\}", lambda match: _text(arguments[int(match[1])]), text)
    return filled.replace("\0", "{").replace("\1", "}")


def _contains(haystack: object, needle: object) -> bool:
    if isinstance(haystack, str):
        return _text(needle).lower() in haystack.lower()
    return any(_same(item, needle) for item in haystack) if isinstance(haystack, list) else False


_FUNCTIONS: dict[str, Callable[..., object]] = {
    "eq": _same,
    "ne": lambda left, right: not _same(left, right),
    "not": lambda value: not _truthy(value),
    "and": lambda *values: all(map(_truthy, values)),
    "or": lambda *values: any(map(_truthy, values)),
    "in": lambda value, *options: any(_same(value, option) for option in options),
    "notin": lambda value, *options: not any(_same(value, option) for option in options),
    "gt": lambda left, right: _number(left) > _number(right),
    "ge": lambda left, right: _number(left) >= _number(right),
    "lt": lambda left, right: _number(left) < _number(right),
    "le": lambda left, right: _number(left) <= _number(right),
    "length": lambda value: len(value) if isinstance(value, (str, list, Mapping)) else 0,
    "format": _format,
    "coalesce": lambda *values: next((value for value in values if value not in (None, "")), None),
    "contains": _contains,
    "startswith": lambda text, prefix: _text(text).lower().startswith(_text(prefix).lower()),
    "endswith": lambda text, suffix: _text(text).lower().endswith(_text(suffix).lower()),
    "lower": lambda text: _text(text).lower(),
    "upper": lambda text: _text(text).upper(),
    "replace": lambda text, old, new: _text(text).replace(_text(old), _text(new)),
    "join": lambda separator, values: _text(separator).join(map(_text, values)) if isinstance(values, list) else "",
}
_COMPARISONS: dict[str, Callable[[object, object], bool]] = {
    "==": _same,
    "!=": lambda left, right: not _same(left, right),
    "<": lambda left, right: _number(left) < _number(right),
    "<=": lambda left, right: _number(left) <= _number(right),
    ">": lambda left, right: _number(left) > _number(right),
    ">=": lambda left, right: _number(left) >= _number(right),
}


def _member(value: object, key: object) -> object:
    if isinstance(value, Mapping):
        return next((item for name, item in value.items() if _same(str(name), _text(key))), None)
    if isinstance(value, list) and isinstance(key, (int, float)) and 0 <= int(key) < len(value):
        return value[int(key)]
    return None


# The predefined variables that depend on the run (`Build.Reason`, `System.PullRequest.TargetBranch`), by their prefix.
_RUN_VARIABLES = frozenset({"agent", "build", "checks", "environment", "pipeline", "release", "resources", "system"})


def _sets(variables: object, name: object) -> bool:
    """Whether `variables` (the scope's) sets the variable `name`."""
    return isinstance(variables, Mapping) and any(_same(str(known), _text(name)) for known in variables)


def _variable(variables: object, name: object) -> object:
    """A variable the pipeline's YAML sets. One of the predefined variables that depend on the run (`Build.Reason`) is
    not known; another it does not set where the template is expanded (a matrix leg's `_BuildConfig`) is empty, as
    Azure evaluates it there."""
    if _sets(variables, name):
        return _member(variables, name)
    if _text(name).partition(".")[0].lower() in _RUN_VARIABLES:
        raise Unevaluated(f"the variable {_text(name)} is not known before the pipeline runs")
    return None


def _referenced(node: Reference, scope: Scope) -> object:
    """`parameters.x.y`, `variables.name`, an `each` loop's `item.name`."""
    root, *path = node.name.split(".")
    if root not in scope:
        raise Unevaluated(f"{root} is not known before the pipeline runs")
    value = scope[root]
    if root == "variables" and path:
        value = _variable(value, path.pop(0))
    for key in path:
        value = _member(value, key)
    return value


def evaluate(node: Node, scope: Scope) -> object:
    """The value of an expression's tree; `Unevaluated` when it names what is not known before the pipeline runs."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Reference):
        return _referenced(node, scope)
    if isinstance(node, Index):
        target, index = evaluate(node.target, scope), evaluate(node.key, scope)
        variables = isinstance(node.target, Reference) and node.target.name == "variables"
        return _variable(target, index) if variables else _member(target, index)
    if isinstance(node, Call):
        function = _FUNCTIONS.get(node.name.lower())
        if function is None:
            raise Unevaluated(f"the function {node.name} is not evaluated")
        return function(*(evaluate(argument, scope) for argument in node.arguments))
    if isinstance(node, Not):
        return not _truthy(evaluate(node.operand, scope))
    if isinstance(node, Comparison):
        return _COMPARISONS[node.operator](evaluate(node.left, scope), evaluate(node.right, scope))
    values = (_truthy(evaluate(operand, scope)) for operand in node.operands)
    return all(values) if node.operator == "&&" else any(values)


# `${{ variables.name }}`, left for the job's variables where the scope does not set it (the pipeline reader
# substitutes them).
_VARIABLE = re.compile(r"\s*variables\.([\w.]+)\s*")


def _value(expression: str, written: str, scope: Scope) -> object:
    variable = _VARIABLE.fullmatch(expression)
    if variable and not _sets(scope.get("variables"), variable[1]):
        return written
    return evaluate(_parsed(expression), scope)


def _scalar(text: str, scope: Scope) -> object:
    """A string with its expressions evaluated: one that is a whole expression is its value (a list, a mapping)."""
    whole = _EXPRESSION.fullmatch(text.strip())
    if whole is not None and text.strip().count("${{") == 1:
        return _value(whole[1], text, scope)
    return _EXPRESSION.sub(lambda match: _text(_value(match[1], match[0], scope)), text)


def _iterated(collection: object) -> Iterable[object]:
    if isinstance(collection, Mapping):
        return ({"key": key, "value": value} for key, value in collection.items())
    return collection if isinstance(collection, list) else ()


# Where an `if`'s chain stands: a branch was taken, or none surely was (a condition not decided may have been).
_TAKEN, _OPEN = "taken", "open"


class _Insertions:
    """The values a sequence of directives inserts, an `if`'s chain followed through its `elseif`s and `else`. A
    condition that cannot be decided before the pipeline runs (a variable it sets as it runs) inserts its branch as
    one it may take, and the branches after it as ones it may take too."""

    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        self.chain: str | None = None

    def _decided(self, condition: str) -> bool | None:
        try:
            return _truthy(evaluate(_parsed(condition), self.scope))
        except Unevaluated:
            return None

    def _branch(self, condition: str | None) -> bool:
        """Whether a branch of the chain may be taken, and where the chain stands after it."""
        if self.chain == _TAKEN:
            return False
        holds = True if condition is None else self._decided(condition)
        if holds is True:
            self.chain = _TAKEN
        return holds is not False

    def inserted(self, key: str, value: object) -> list[object] | None:
        """What a key inserts (None for a key that is no directive)."""
        directive = _DIRECTIVE.fullmatch(key.strip())
        if directive is None:
            self.chain = None
            return None
        kind, rest = directive["kind"], directive["rest"]
        if kind in ("if", "elseif", "else"):
            if kind == "if":
                self.chain = _OPEN
            elif self.chain is None:
                raise Unevaluated(f"an {kind} follows no if")
            taken = self._branch(None if kind == "else" else rest)
            if kind == "else":
                self.chain = None
            return [expand(value, self.scope)] if taken else []
        if kind == "each" and (each := _EACH.fullmatch(rest)) is not None:
            self.chain = None
            collection = evaluate(_parsed(each["collection"]), self.scope)
            return [expand(value, {**self.scope, each["name"]: item}) for item in _iterated(collection)]
        raise Unevaluated(f"${{{{ {kind} }}}} is not evaluated")


def expand(value: object, scope: Scope) -> object:
    """A template's YAML with its expressions evaluated and its directives expanded."""
    if isinstance(value, str):
        return _scalar(value, scope)
    if isinstance(value, list):
        return _expanded_sequence(value, scope)
    if isinstance(value, Mapping):
        return _expanded_mapping(value, scope)
    return value


def _expanded_mapping(value: Mapping[object, object], scope: Scope) -> dict[str, object]:
    found: dict[str, object] = {}
    insertions = _Insertions(scope)
    for key, item in value.items():
        inserted = insertions.inserted(str(key), item)
        if inserted is None:
            found[_text(_scalar(str(key), scope))] = expand(item, scope)
            continue
        for mapping in inserted:
            if not isinstance(mapping, Mapping):
                raise Unevaluated("a directive in a mapping inserts no mapping")
            found.update(mapping)
    return found


def _expanded_sequence(value: list[object], scope: Scope) -> list[object]:
    found: list[object] = []
    insertions = _Insertions(scope)
    for item in value:
        key = next(iter(item), None) if isinstance(item, Mapping) and len(item) == 1 else None
        inserted = insertions.inserted(str(key), item[key]) if key is not None else None  # type: ignore[index]
        if inserted is None:
            insertions.chain = None
            found.append(expand(item, scope))
            continue
        for insertion in inserted:
            found.extend(insertion if isinstance(insertion, list) else [insertion])
    return found
