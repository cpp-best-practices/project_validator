"""Facts placed where the YAML file they were read from has them.

The CI readers and the command expanders name the place of what they find by its keys in a YAML document
(`("jobs", "test", "steps", 3, "run")`): `Placed` finds where the file has that place (see
`project_validator.yaml_support.places`) and puts it on the fact's origin, and on those of the commands that ran a
command. A fact read from a file that is not YAML, already placed, or whose place the file does not have, is left as
it is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from project_validator import yaml_support
from project_validator.facts import Command, Fact, Origin
from project_validator.parsing import Span

_YAML = (".yml", ".yaml")


class Placed:
    """Places facts, reading each YAML file once (`read`: its text, or None when the project does not hold it)."""

    def __init__(self, read: Callable[[str], str | None]) -> None:
        self.read = read
        self.places: dict[str, Callable[[yaml_support.Place], Span | None]] = {}

    def fact(self, fact: Fact) -> Fact:
        origin = self.origin(fact.origin)
        if isinstance(fact, Command) and fact.via:
            return replace(fact, origin=origin, via=tuple(map(self.origin, fact.via)))
        return fact if origin is fact.origin else replace(fact, origin=origin)

    def origin(self, origin: Origin) -> Origin:
        if origin.span is not None or not origin.at or not origin.path.endswith(_YAML):
            return origin
        if origin.path not in self.places:
            self.places[origin.path] = yaml_support.places(self.read(origin.path) or "")
        span = self.places[origin.path](origin.at)
        return origin if span is None else replace(origin, span=span)


__all__ = ["Placed"]
