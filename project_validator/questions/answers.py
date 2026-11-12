"""Every question's answers about one project, as JSON-ready data (`--answers`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_validator.questions import known_questions

if TYPE_CHECKING:
    from project_validator.core import Context


def answers(context: Context) -> dict[str, object]:
    """For each question, its answer for each of the project's languages and formats."""
    names = sorted(context.structure.languages_and_formats)
    return {
        question.name: [question.answer(name, context.facts).as_dict() for name in names]
        for question in known_questions()
    }


__all__ = ["answers"]
