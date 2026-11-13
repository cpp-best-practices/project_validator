"""Every question's answers about one project, as JSON-ready data (`--answers`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from project_validator.questions import Answer, Answered, LanguageAnswers, known_questions

if TYPE_CHECKING:
    from project_validator.core import Context
    from project_validator.ecosystems import Kind


def _listed(found: Answered, kind: Kind) -> bool:
    """A language's answer is listed whatever it is; a format's only where some unit has an answer a tool could give:
    every project holds YAML, which nothing tests, scans or audits, and that is not worth a line per question."""
    if kind == "language" or not isinstance(found, LanguageAnswers):
        return True
    units: tuple[Any, ...] = found.units
    return any(unit.answer is not Answer.IMPOSSIBLE for unit in units)


def answers(context: Context) -> dict[str, object]:
    """For each question, its answer for each of the project's languages, and formats, that it is about."""
    structure = context.structure
    names = {"language": sorted(structure.languages), "format": sorted(structure.formats)}
    return {
        question.name: [
            found.as_dict()
            for kind in ("language", "format")
            if kind in question.kinds
            for name in names[kind]
            if _listed(found := question.answer(name, context.facts), kind)
        ]
        for question in known_questions()
    }


__all__ = ["answers"]
