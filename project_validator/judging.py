"""Checks made of a question and its policy: each language (or format) the project uses is judged in each unit that
has it, and the results are named by language, by unit, or by both, as far as they differ.

One result stands for several (`combined`): what was skipped is left out unless everything was, one result is
said once when all agree, and otherwise each is labelled and the worst status wins.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from project_validator.components import component_cache
from project_validator.core import Check, Context, Placed, Result, Status
from project_validator.ecosystems import Ecosystem, ecosystems_for, registered
from project_validator.facts import Facts
from project_validator.facts.tools import handling
from project_validator.policy import Judge
from project_validator.questions import LanguageAnswers, RanTools, UnitAnswer


def labelled(results: Mapping[str, Result]) -> Result:
    """One result for several subjects, each named by its label: the worst status wins."""
    return Result(
        status=max((result.status for result in results.values()), key=lambda status: status.severity),
        message="; ".join(f"{label}: {result.message}" for label, result in results.items()),
        details=tuple(f"{label}: {detail}" for label, result in results.items() for detail in result.details),
    )


def combined[K](results: Mapping[K, Result], *, label: Callable[[K, tuple[K, ...]], str], none: str) -> Result:
    """One result for several subjects: skipped with `none` when there are none; the skipped ones left out, unless
    all are; the one result when all agree; otherwise each labelled (`label` is given the subject and every subject
    kept, to name it as far as it differs from the others) and the worst status wins."""
    if not results:
        return Result.skipped(none)
    if judged_ := {key: result for key, result in results.items() if result.status is not Status.SKIP}:
        results = judged_
    if len(set(results.values())) == 1:
        return next(iter(results.values()))
    kept = tuple(results)
    return labelled({label(key, kept): result for key, result in results.items()})


def _auxiliary_only(result: Result) -> tuple[str, ...]:
    """What named the auxiliary code a result is about, when every place of it is auxiliary code; else nothing."""
    if not result.places or not all(place.auxiliary for place in result.places):
        return ()
    return tuple(sorted({name for place in result.places for name in place.auxiliary}))


def _ecosystem_label(ecosystem: Ecosystem, result: Result) -> str:
    named = _auxiliary_only(result)
    return f"{ecosystem.label} (auxiliary: {', '.join(named)})" if named else ecosystem.label


def by_ecosystem(results: Mapping[Ecosystem, Result]) -> Result:
    """One result for several ecosystems, labelled by ecosystem where they differ; a result about an ecosystem's
    auxiliary code alone is always labelled, with what named that code."""
    folded = combined(
        results,
        label=lambda ecosystem, _: _ecosystem_label(ecosystem, results[ecosystem]),
        none="no recognised ecosystem in the project",
    )
    judged_ = [ecosystem for ecosystem, result in results.items() if result.status is not Status.SKIP]
    if len(judged_) == 1 and _auxiliary_only(results[judged_[0]]) and folded.status is not Status.SKIP:
        folded = labelled({_ecosystem_label(judged_[0], results[judged_[0]]): folded})
    places = tuple(
        replace(place, ecosystem=ecosystem.label)
        for ecosystem, result in results.items()
        for place in result.places or (Placed(ecosystem="", unit="", result=result),)
    )
    return replace(folded, places=places)


def check_each_ecosystem[Rules](
    context: Context, rules: Mapping[Ecosystem, Rules], judge: Callable[[Rules, Context], Result]
) -> Result:
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled."""
    used = ecosystems_for(context.structure.languages_and_formats, rules)
    return by_ecosystem({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})


type _Place = tuple[str, str]  # (language, unit)
type _Auxiliary = Mapping[_Place, tuple[str, ...]]  # what named the auxiliary code a place's answer is about
type _Found[A] = list[tuple[A, tuple[str, ...]]]  # each answer with what named its code (nothing: the product's)

_ADVISORY = "a warning, not a failure: the {language} here is auxiliary code ({named})"


def _label(place: _Place, places: tuple[_Place, ...], auxiliary: _Auxiliary) -> str:
    """How a result is named among the others: by language, by unit, or by both, as far as they differ; and by what
    named the auxiliary code it is about, when it is."""
    language, unit = place
    languages, units = {language for language, _ in places}, {unit for _, unit in places}
    where = "the root" if unit == "." else unit
    name = language if len(units) == 1 else where if len(languages) == 1 else f"{language} in {where}"
    return f"{name} (auxiliary: {', '.join(named)})" if (named := auxiliary.get(place)) else name


def _advisory(result: Result, language: str, named: tuple[str, ...]) -> Result:
    """A failure of auxiliary code alone is a warning that says so, and what named the code (`--auxiliary ...`)."""
    if result.status is not Status.FAIL:
        return result
    by = " ".join(f"--auxiliary {name}" for name in named)
    return replace(result, status=Status.WARN, details=(*result.details, _ADVISORY.format(language=language, named=by)))


def _found[A: UnitAnswer](
    languages: frozenset[str], context: Context, answers: Callable[[str, Facts], LanguageAnswers[A]]
) -> _Found[A]:
    found: _Found[A] = []
    for language in sorted(languages & context.structure.languages_and_formats):
        answered = answers(language, context.facts)
        found += [(answer, answered.auxiliary.get(answer.unit, ())) for answer in answered.units]
    return found


def judged[A: UnitAnswer](
    languages: frozenset[str],
    context: Context,
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
) -> Result:
    """The policy's judgement of each of `languages` the project uses, in each unit that has it; one result when they
    agree. A language the practice does not apply to (C in a C++ project) says nothing beside those it does. A result
    about auxiliary code alone (what `--auxiliary` named) is advisory (`_advisory`), and labelled with what named the
    code where results are labelled (`by_ecosystem` labels an ecosystem's result about auxiliary code alone always).
    Places are named by `by_ecosystem`; a result returned from here alone has unnamed places."""
    found = _found(languages, context, answers)
    auxiliary: _Auxiliary = {(answer.language, answer.unit): named for answer, named in found if named}
    results: dict[_Place, Result] = {}
    for answer, named in found:
        result = judge(answer, allow_unknown=context.options.allow_unknown)
        results[(answer.language, answer.unit)] = _advisory(result, answer.language, named) if named else result
    none = "no unit of the project is written in these languages"
    folded = combined(results, label=lambda place, kept: _label(place, kept, auxiliary), none=none)
    units = dict.fromkeys(unit for _, unit in results)
    return replace(folded, places=tuple(_placed(unit, results, found, auxiliary) for unit in units))


def _tools_ran(answer: object) -> tuple[str, ...]:
    """The tools CI ran for an answer, when it says (not every answer is about tools)."""
    return answer.tools_ran() if isinstance(answer, RanTools) else ()


def _placed[A: UnitAnswer](
    unit: str, results: Mapping[_Place, Result], found: _Found[A], auxiliary: _Auxiliary
) -> Placed:
    """One unit's result across the languages judged there, with the tools that ran for the practice in it, and what
    named the auxiliary code the result is about, when it is."""
    here = {language: result for (language, where), result in results.items() if where == unit}
    named = sorted({name for (_, where), found_ in auxiliary.items() if where == unit for name in found_})
    return Placed(
        ecosystem="",
        unit=unit,
        result=combined(here, label=lambda language, _: language, none=""),
        tools=tuple(dict.fromkeys(tool for answer, _ in found if answer.unit == unit for tool in _tools_ran(answer))),
        auxiliary=tuple(named),
    )


def answered_check[A: UnitAnswer](
    *,
    name: str,
    description: str,
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
    aspect: str | None = None,
    languages: Callable[[], frozenset[str]] | None = None,
    aliases: tuple[str, ...] = (),
) -> Check:
    """A check that judges a question's answers by a policy, for each ecosystem the project uses (its findings
    labelled by ecosystem as other checks' are). It applies to the languages its known tools handle (`aspect`), or to
    `languages`."""
    if languages is None:
        if aspect is None:
            raise TypeError("answered_check needs an aspect or languages")
        languages = handling(aspect)
    handled = component_cache(languages)

    def run(context: Context) -> Result:
        now = handled()
        by_ecosystem_ = {e: e.languages & now for e in registered() if e.languages & now}
        return check_each_ecosystem(
            context, by_ecosystem_, lambda judged_languages, found: judged(judged_languages, found, answers, judge)
        )

    return Check(name=name, description=description, run=run, languages_from=handled, aspect=aspect, aliases=aliases)


__all__ = ["answered_check", "by_ecosystem", "check_each_ecosystem", "combined", "judged", "labelled"]
