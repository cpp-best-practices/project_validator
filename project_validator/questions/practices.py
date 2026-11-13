"""The settings questions: for each language, which of the settings a practice asks for (the strict warning set,
warnings as errors) are met, and where; for each compiler CI builds with, where a practice is judged per compiler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from project_validator.facts import Facts
from project_validator.facts.practices import (
    Practice,
    PracticeName,
    Texts,
    ci_texts,
    met,
    practices_of,
)
from project_validator.questions import (
    EVERY_KIND,
    Answer,
    LanguageAnswers,
    Question,
    answer_dict,
    language_wide,
    unknowns_for,
)


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
    skipped: str | None = None

    def found(self) -> tuple[str, ...]:
        """Every requirement met for some compiler, in order."""
        return tuple(dict.fromkeys(name for compiled in self.compiled for name, _ in compiled.found))

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            practice=self.practice.name,
            compilers=[compiled.as_dict() for compiled in self.compiled],
            unknowns=list(self.unknowns),
        )


def _compiled(practice: Practice, facts: Facts, compiler: str | None, texts: Texts) -> Compiled:
    found: list[tuple[str, tuple[str, ...]]] = []
    missing: list[str] = []
    for requirement in practice.requirements(facts, compiler):
        if evidence := met(practice, requirement, facts, compiler, texts):
            found.append((requirement.name, tuple(str(where) for where in evidence)))
        else:
            missing.append(requirement.name)
    return Compiled(compiler=compiler, found=tuple(found), missing=tuple(missing))


def _met(practice: Practice, compiled: tuple[Compiled, ...]) -> bool:
    if practice.forbids:
        return not any(compiled_for.found for compiled_for in compiled)
    if practice.any_one:
        return any(compiled_for.found for compiled_for in compiled)
    return bool(compiled) and all(not compiled_for.missing for compiled_for in compiled)


def _answer(practice: Practice, met: bool, unknown: bool) -> Answer:
    """What was not read may hide a requirement met, or (for a practice that forbids them) one that is not."""
    in_doubt = met if practice.forbids else not met
    if in_doubt and unknown:
        return Answer.UNKNOWN
    return Answer.YES if met else Answer.NO


def practice_answer(name: str, language: str, facts: Facts) -> PracticeAnswer | None:
    """Whether CI (or the build) meets the practice called `name` for `language`; None when nothing asks it of
    `language`."""
    practices = practices_of(name, language)
    if not practices:
        return None
    practice = practices[0]
    if (skipped := practice.skipped(facts)) is not None:
        return PracticeAnswer(
            language=language, unit=".", practice=practice, answer=Answer.IMPOSSIBLE, compiled=(), skipped=skipped
        )
    compilers = practice.compilers(facts) if practice.compilers else (None,)
    texts = ci_texts(facts)
    compiled = tuple(_compiled(practice, facts, compiler, texts) for compiler in compilers)
    unknowns = unknowns_for((), facts, reads=practice.reads)
    answer = _answer(practice, _met(practice, compiled), bool(unknowns))
    return PracticeAnswer(
        language=language, unit=".", practice=practice, answer=answer, compiled=compiled, unknowns=unknowns
    )


def practice_answers(name: str) -> Callable[[str, Facts], LanguageAnswers[PracticeAnswer]]:
    def answers(language: str, facts: Facts) -> LanguageAnswers[PracticeAnswer]:
        return language_wide(language, facts, lambda: practice_answer(name, language, facts))

    return answers


warning_answers = practice_answers(PracticeName.WARNINGS)
error_answers = practice_answers(PracticeName.WARNINGS_AS_ERRORS)
hardening_answers = practice_answers(PracticeName.HARDENING)
extension_answers = practice_answers(PracticeName.EXTENSIONS)
sanitizer_answers = practice_answers(PracticeName.SANITIZERS)
out_of_source_answers = practice_answers(PracticeName.OUT_OF_SOURCE)
compile_commands_answers = practice_answers(PracticeName.COMPILE_COMMANDS)
top_level_guard_answers = practice_answers(PracticeName.TOP_LEVEL_GUARD)

WARNINGS_QUESTION = Question(
    name=PracticeName.WARNINGS,
    description="Which of the strict warning settings each language asks for are on?",
    answer=warning_answers,
)
HARDENING_QUESTION = Question(
    name=PracticeName.HARDENING,
    description="Which of the hardening settings each language asks for are on?",
    answer=hardening_answers,
)
WARNINGS_AS_ERRORS_QUESTION = Question(
    name=PracticeName.WARNINGS_AS_ERRORS,
    description="Do warnings fail the build for each language?",
    answer=error_answers,
    kinds=EVERY_KIND,
)
EXTENSIONS_QUESTION = Question(
    name=PracticeName.EXTENSIONS,
    description="Are compiler extensions to the language standard turned off for each compiled language?",
    answer=extension_answers,
)
SANITIZERS_QUESTION = Question(
    name=PracticeName.SANITIZERS,
    description="Which of the sanitizers each language asks for are used in some configuration?",
    answer=sanitizer_answers,
)
OUT_OF_SOURCE_QUESTION = Question(
    name=PracticeName.OUT_OF_SOURCE,
    description="Does the build prevent in-source builds?",
    answer=out_of_source_answers,
)
COMPILE_COMMANDS_QUESTION = Question(
    name=PracticeName.COMPILE_COMMANDS,
    description="Does the build export compile_commands.json?",
    answer=compile_commands_answers,
)
TOP_LEVEL_GUARD_QUESTION = Question(
    name=PracticeName.TOP_LEVEL_GUARD,
    description="Are tests and developer-only settings guarded for use as a subproject?",
    answer=top_level_guard_answers,
)

__all__ = [
    "COMPILE_COMMANDS_QUESTION",
    "EXTENSIONS_QUESTION",
    "HARDENING_QUESTION",
    "OUT_OF_SOURCE_QUESTION",
    "SANITIZERS_QUESTION",
    "TOP_LEVEL_GUARD_QUESTION",
    "WARNINGS_AS_ERRORS_QUESTION",
    "WARNINGS_QUESTION",
    "Compiled",
    "PracticeAnswer",
    "compile_commands_answers",
    "extension_answers",
    "out_of_source_answers",
    "practice_answer",
    "practice_answers",
    "sanitizer_answers",
    "top_level_guard_answers",
]
