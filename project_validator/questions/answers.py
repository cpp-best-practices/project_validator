"""Every question's answers about one project, as JSON-ready data (`--answers`)."""

from typing import TYPE_CHECKING

from project_validator.questions import built_in_questions

if TYPE_CHECKING:
    from project_validator.core import Context


def answers(context: Context) -> dict[str, object]:
    """For each question, its answer for each of the project's languages."""
    languages = sorted(context.structure.languages)
    return {
        question.name: [question.answer(language, context.facts).as_dict() for language in languages]
        for question in built_in_questions()
    }


__all__ = ["answers"]
