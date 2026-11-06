"""Questions: queries over the fact database, each answering one thing about the project per language.

Answers are the stable, machine-readable interface (`--answers`); checks judge them by a policy and never read
extractors (see docs/architecture.md).
"""

import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from project_validator.facts import Facts


class Answer(enum.StrEnum):
    """`impossible`: no known tool can provide it for the language. `unknown`: something that could provide it was
    not read (see `project_validator.facts.Unknown`)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    IMPOSSIBLE = "impossible"


class Answered(Protocol):
    def as_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Question:
    """A question about the project, answered per language from the facts. Questions are found, never listed."""

    name: str
    description: str
    answer: Callable[[str, Facts], Answered]


def built_in_questions() -> tuple[Question, ...]:
    """Every question defined by a module of `project_validator.questions`."""
    from project_validator.components import built_in

    return built_in(Question)


__all__ = ["Answer", "Answered", "Question", "built_in_questions"]
