"""Questions: queries over the fact database, each answering one thing about the project per language (or format: a
format is asked what its tools can answer, and is a language to every question), in each unit of the project that
has the language.

Answers are the stable, machine-readable interface (`--answers`); checks judge them by a policy and never read
extractors (see docs/architecture.md). What every question needs (the units of a language, the runs of an aspect in
a unit, the unknowns that matter to some tools) is here, once.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from project_validator.components import known
from project_validator.ecosystems import Kind
from project_validator.facts import Facts, Unknown
from project_validator.facts.auxiliary import Selectors, selectors
from project_validator.facts.structure import SourceFile, Unit
from project_validator.facts.tools import Tool, ToolRun, owner


class Answer(enum.StrEnum):
    """`impossible`: no known tool can provide it for the language. `unknown`: something that could provide it was
    not read (see `project_validator.facts.Unknown`)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    IMPOSSIBLE = "impossible"


class Answered(Protocol):
    def as_dict(self) -> dict[str, object]: ...


@runtime_checkable
class RanTools(Protocol):
    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran for the practice in this unit, each once, in order."""
        ...


class UnitAnswer(Answered, Protocol):
    @property
    def unit(self) -> str: ...

    @property
    def language(self) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageAnswers[A: UnitAnswer]:
    """A question's answers for one language, one per unit of the project that has it; when no unit has the language
    as the product's, one per unit whose auxiliary code (what `--auxiliary` named) is written in it, and `auxiliary`
    says what named that code by unit, for the judging layer to make the answers advisory."""

    language: str
    units: tuple[A, ...]
    auxiliary: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "units": [unit.as_dict() for unit in self.units],
            "auxiliary": {unit: list(roles) for unit, roles in self.auxiliary.items()},
        }


def units_of(language: str, facts: Facts) -> tuple[str, ...]:
    """The units of the project whose own code has `language` (or whose own files are in that format): every unit
    but the vendored ones, whatever its role (a `tools/` module is held to every practice as the product is), until
    `--auxiliary` names its code; none when the language is only in code `--auxiliary` names. A project with no
    units is one, its root."""
    units = facts.of(Unit)
    if not units:
        return (".",)
    return tuple(unit.directory for unit in units if language in unit.languages or language in unit.formats)


def auxiliary_units_of(language: str, facts: Facts) -> dict[str, tuple[str, ...]]:
    """The units whose auxiliary code (what `--auxiliary` named; never other projects' vendored code) is written in
    `language`, each with what named that code: what a practice holds a language to when no unit has it as the
    product's, as advisory."""
    units = [found.directory for found in facts.of(Unit)] or ["."]
    named = selectors(facts)
    found: dict[str, set[str]] = {}
    for source in facts.of(SourceFile):
        if source.language == language and not source.vendored and (by := named.matching(source.path, language)):
            found.setdefault(owner(source.path, units), set()).add(by)
    return {unit: tuple(sorted(by)) for unit, by in sorted(found.items())}


def per_unit[A: UnitAnswer](
    language: str, facts: Facts, answer: Callable[[str, tuple[str, ...]], A]
) -> LanguageAnswers[A]:
    """The answer for `language` in each unit that has it, or, when no unit has it as the product's, in each unit
    whose auxiliary code is written in it. `answer` is given the unit and what named the auxiliary code the answer is
    about (nothing for the product's code)."""
    if units := units_of(language, facts):
        return LanguageAnswers(language=language, units=tuple(answer(unit, ()) for unit in units))
    auxiliary = auxiliary_units_of(language, facts)
    units_ = tuple(answer(unit, named) for unit, named in auxiliary.items())
    return LanguageAnswers(language=language, units=units_, auxiliary=auxiliary)


def language_wide[A: UnitAnswer](language: str, facts: Facts, answer: Callable[[], A | None]) -> LanguageAnswers[A]:
    """A language-wide question's answer (about the whole project, as the root unit's; None when the question does not
    apply to the language). When only auxiliary code is written in the language, the answer is about that code."""
    found = answer()
    units = () if found is None else (found,)
    if found is None or units_of(language, facts):
        return LanguageAnswers(language=language, units=units)
    named = sorted({name for names in auxiliary_units_of(language, facts).values() for name in names})
    return LanguageAnswers(language=language, units=units, auxiliary={".": tuple(named)} if named else {})


def _auxiliary(run: ToolRun, language: str, concerns: frozenset[str], named: Selectors) -> bool:
    """Whether a run is only in auxiliary code (tsc in `examples/app`, with `--auxiliary example`) the answer is not
    about (`concerns`: what named the code it is about), which says nothing about the code it is."""
    by = {named.matching(scope, language, directory=True) for scope in run.scope}
    return bool(by) and "" not in by and not (by & concerns)


def runs_of(
    aspect: str, language: str, unit: str, facts: Facts, *, auxiliary: Iterable[str] = ()
) -> tuple[ToolRun, ...]:
    """The runs CI makes of tools that provide `aspect` for `language` in `unit` (see `ToolRun.covers`), but runs
    only in auxiliary code `--auxiliary` names, unless the answer is about that code (`auxiliary`: what named it)."""
    units = [found.directory for found in facts.of(Unit)] or ["."]
    concerns, named = frozenset(auxiliary), selectors(facts)
    return tuple(
        run
        for run in facts.of(ToolRun)
        if aspect in run.provides
        and language in run.languages
        and run.covers(unit, units)
        and not _auxiliary(run, language, concerns, named)
    )


def unknowns_for(
    tools: Iterable[Tool],
    facts: Facts,
    *,
    hiding: Iterable[str] = ("jobs", "commands", "settings"),
    reads: Iterable[str] = (),
) -> tuple[str, ...]:
    """What was not read that may hide a run (a job or a command), or the settings the `tools` read (or those of
    `reads`, for a question that reads settings without a tool), as `subject: reason (origin)`; only what may hide one
    of `hiding`."""
    read = {name for tool in tools for name in (tool.name, *tool.reads)} | set(reads)
    kinds = frozenset(hiding)
    return tuple(
        f"{fact.subject}: {fact.reason} ({fact.origin})"
        for fact in facts.of(Unknown)
        if fact.hides in kinds and (fact.hides != "settings" or read & set(fact.tools))
    )


def answer_dict(answer: UnitAnswer, verdict: Answer | None = None, /, **fields: object) -> dict[str, object]:
    """An answer as JSON-ready data: its language and unit, its verdict when it has one, then its own `fields`."""
    found: dict[str, object] = {"language": answer.language, "unit": answer.unit}
    if verdict is not None:
        found["answer"] = str(verdict)
    return {**found, **fields}


LANGUAGES: frozenset[Kind] = frozenset({"language"})
FORMATS: frozenset[Kind] = frozenset({"format"})


@dataclass(frozen=True, slots=True, kw_only=True)
class Question:
    """A question about the project, answered per language from the facts, for the `kinds` of ecosystem it is about:
    languages (the default), formats (what parses), or both (what is formatted). Questions are found, never listed."""

    name: str
    description: str
    answer: Callable[[str, Facts], Answered]
    kinds: frozenset[Kind] = LANGUAGES


def known_questions() -> tuple[Question, ...]:
    """Every question defined by a module of `project_validator.questions`."""
    return known(Question)


__all__ = [
    "FORMATS",
    "LANGUAGES",
    "Answer",
    "Answered",
    "LanguageAnswers",
    "Question",
    "RanTools",
    "UnitAnswer",
    "answer_dict",
    "auxiliary_units_of",
    "known_questions",
    "language_wide",
    "per_unit",
    "runs_of",
    "units_of",
    "unknowns_for",
]
