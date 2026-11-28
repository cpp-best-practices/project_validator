"""A detail shown about a project without being judged (upstream #412)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from project_validator.ecosystems import formats
from project_validator.facts import Fact, Facts
from project_validator.facts.roles import role
from project_validator.facts.structure import SourceFile


@dataclass(frozen=True, slots=True, kw_only=True)
class Detail:
    """One thing shown about the project: its `group` ("Versions"), what it is about (`subject`: "Python"), what is
    said of it in words, and the same as data for the JSON."""

    group: str
    subject: str
    text: str
    data: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"group": self.group, "subject": self.subject, "text": self.text, "data": dict(self.data)}


def own_code(facts: Facts) -> list[SourceFile]:
    """The project's own code: its sources in a language (not a format), other projects' vendored code left out."""
    known = formats()
    return [
        source
        for source in facts.of(SourceFile)
        if not source.vendored and source.language is not None and source.language not in known
    ]


def in_product[F: Fact](facts: Iterable[F]) -> list[F]:
    """The facts found in the product's own files: not in its tests' fixtures, nor in vendored code."""
    return [fact for fact in facts if role(fact.origin.path) == "product"]


def and_more(count: int) -> str:
    """` and 3 more`, for the rest of a list named by its first; "" when there is no rest."""
    return f" and {count} more" if count > 0 else ""


__all__ = ["Detail", "and_more", "in_product", "own_code"]
