"""Policy: how answers (see `project_validator.questions`) are judged, one module per practice. Built in, apart from
`--allow-unknown`; kept apart from the questions so that it can be made configurable without touching extraction.

An unknown answer is a gap in the validator's tooling (configuration it cannot read), not a finding about the
project, so it is an error unless the user allows unknowns; then it is judged by what could be read.
"""

from collections.abc import Iterable

from project_validator.core import Result, Status

_ALLOW_UNKNOWN = "--allow-unknown judges only what could be read"


def unknown(message: str, unknowns: Iterable[str], *details: str) -> Result:
    """The error an unknown answer is: what could not be read, then what could."""
    return Result(
        status=Status.ERROR,
        message=f"{message} is unknown: some of what it runs could not be read",
        details=(*(f"not read: {found}" for found in unknowns), *details, _ALLOW_UNKNOWN),
    )


def either(items: Iterable[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    items = list(items)
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


def both(items: Iterable[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    items = list(items)
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def alternatives(ways: Iterable[str]) -> str:
    """`a`, or `a (or b, c)`: the first way, and the others."""
    ways = list(ways)
    return ways[0] if len(ways) == 1 else f"{ways[0]} (or {either(ways[1:])})"


__all__ = ["alternatives", "both", "either", "unknown"]
