"""Every question's answers about one project, as JSON-ready data (`--answers`)."""

from typing import TYPE_CHECKING

from project_validator.facts.coverage import built_in_coverage_tools
from project_validator.questions.coverage import coverage_answer

if TYPE_CHECKING:
    from project_validator.core import Context


def answers(context: Context) -> dict[str, object]:
    """For each question, its answer for each of the project's languages."""
    tools = built_in_coverage_tools()
    languages = sorted(context.structure.languages)
    return {"coverage": [coverage_answer(language, context.facts, tools).as_dict() for language in languages]}


__all__ = ["answers"]
