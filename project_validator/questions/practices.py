"""The settings questions: for each language, which of the settings a practice asks for (the strict warning set,
warnings as errors) are met, and where; for each compiler CI builds with, where a practice is judged per compiler."""

from collections.abc import Callable
from dataclasses import dataclass

from project_validator.facts import Facts, Unknown
from project_validator.facts.practices import (
    WARNINGS,
    WARNINGS_AS_ERRORS,
    Practice,
    Texts,
    ci_texts,
    met,
    practices_of,
)
from project_validator.questions import Answer, LanguageAnswers, Question


@dataclass(frozen=True, slots=True, kw_only=True)
class Compiled:
    """For one compiler (None: the language has none to tell apart), the requirements met (each with where) and those
    missing."""

    compiler: str | None
    found: tuple[tuple[str, tuple[str, ...]], ...]
    missing: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"compiler": self.compiler, "found": dict(self.found), "missing": list(self.missing)}


@dataclass(frozen=True, slots=True, kw_only=True)
class PracticeAnswer:
    language: str
    unit: str
    practice: Practice
    answer: Answer
    compiled: tuple[Compiled, ...]
    unknowns: tuple[str, ...] = ()

    def found(self) -> tuple[str, ...]:
        """Every requirement met for some compiler, in order."""
        return tuple(dict.fromkeys(name for compiled in self.compiled for name, _ in compiled.found))

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "unit": self.unit,
            "practice": self.practice.name,
            "answer": self.answer.value,
            "compilers": [compiled.as_dict() for compiled in self.compiled],
            "unknowns": list(self.unknowns),
        }


def _compiled(practice: Practice, facts: Facts, compiler: str | None, texts: Texts) -> Compiled:
    found: list[tuple[str, tuple[str, ...]]] = []
    missing: list[str] = []
    for requirement in practice.requirements(facts, compiler):
        if evidence := met(practice, requirement, facts, compiler, texts):
            found.append((requirement.name, tuple(str(where) for where in evidence)))
        else:
            missing.append(requirement.name)
    return Compiled(compiler=compiler, found=tuple(found), missing=tuple(missing))


def _unknowns(practice: Practice, facts: Facts) -> tuple[str, ...]:
    """What was not read that may hide a command, or a setting of the files the practice reads."""
    hidden = (
        fact
        for fact in facts.of(Unknown)
        if fact.hides in ("jobs", "commands") or (fact.hides == "settings" and set(fact.tools) & set(practice.reads))
    )
    return tuple(f"{fact.subject}: {fact.reason} ({fact.origin})" for fact in hidden)


def _met(practice: Practice, compiled: tuple[Compiled, ...]) -> bool:
    if practice.any_one:
        return any(compiled_for.found for compiled_for in compiled)
    return bool(compiled) and all(not compiled_for.missing for compiled_for in compiled)


def practice_answer(name: str, language: str, facts: Facts) -> PracticeAnswer | None:
    """Whether CI (or the build) meets the practice called `name` for `language`; None when nothing asks it of
    `language`."""
    practices = practices_of(name, language)
    if not practices:
        return None
    practice = practices[0]
    compilers = practice.compilers(facts) if practice.compilers else (None,)
    texts = ci_texts(facts)
    compiled = tuple(_compiled(practice, facts, compiler, texts) for compiler in compilers)
    unknowns = _unknowns(practice, facts)
    answer = Answer.YES if _met(practice, compiled) else Answer.UNKNOWN if unknowns else Answer.NO
    return PracticeAnswer(
        language=language, unit=".", practice=practice, answer=answer, compiled=compiled, unknowns=unknowns
    )


def _answers(name: str) -> Callable[[str, Facts], LanguageAnswers[PracticeAnswer]]:
    def answers(language: str, facts: Facts) -> LanguageAnswers[PracticeAnswer]:
        found = practice_answer(name, language, facts)
        return LanguageAnswers(language=language, units=() if found is None else (found,))

    return answers


warning_answers = _answers(WARNINGS)
error_answers = _answers(WARNINGS_AS_ERRORS)

WARNINGS_QUESTION = Question(
    name=WARNINGS,
    description="Which of the strict warning settings each language asks for are on?",
    answer=warning_answers,
)
WARNINGS_AS_ERRORS_QUESTION = Question(
    name=WARNINGS_AS_ERRORS, description="Do warnings fail the build for each language?", answer=error_answers
)

__all__ = ["WARNINGS_AS_ERRORS_QUESTION", "WARNINGS_QUESTION", "Compiled", "PracticeAnswer", "practice_answer"]
