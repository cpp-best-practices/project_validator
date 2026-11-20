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
from project_validator.facts.roles import AUXILIARY
from project_validator.facts.structure import SourceFile, Unit
from project_validator.facts.tools import handling
from project_validator.policy import Judge
from project_validator.questions import AdvisedTools, LanguageAnswers, RanTools, UnitAnswer


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


_COMPANION = "a warning, not a failure: the {label} is not the product"


def _companions(results: Mapping[Ecosystem, Result], facts: Facts) -> dict[Ecosystem, Result]:
    """The results with a companion ecosystem's failure (a documentation site's) a warning that says so, when a
    language with sources other than the companions' own configuration (a site's conf.py) is judged: the product's
    results decide the project."""
    companions = [ecosystem.companion for ecosystem in results if ecosystem.companion is not None]
    products = {
        source.language
        for source in facts.of(SourceFile)
        if source.language and not any(pattern.search(source.path) for pattern in companions)
    }
    if not any(
        ecosystem.kind == "language" and ecosystem.languages & products and result.status is not Status.SKIP
        for ecosystem, result in results.items()
    ):
        return dict(results)
    return {
        ecosystem: _warned(result, _COMPANION.format(label=ecosystem.label.lower()))
        if ecosystem.companion is not None
        else result
        for ecosystem, result in results.items()
    }


def _warned(result: Result, why: str) -> Result:
    """A failure as a warning that says `why`, its places' failures too; any other result as it is."""
    if result.status is not Status.FAIL:
        return result
    places = tuple(replace(place, result=_warned(place.result, why)) for place in result.places)
    return replace(result, status=Status.WARN, details=(*result.details, why), places=places)


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
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled. A
    companion ecosystem's failure beside a product language is a warning (`_companions`)."""
    used = ecosystems_for(context.structure.languages_and_formats, rules)
    results = {ecosystem: judge(rules[ecosystem], context) for ecosystem in used}
    return by_ecosystem(_companions(results, context.facts))


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
    by = " ".join(f"--auxiliary {name}" for name in named)
    return _warned(result, _ADVISORY.format(language=language, named=by))


_AUXILIARY_UNIT = "a warning, not a failure: {unit} is {role} code, not the product's"


def _auxiliary_roles(facts: Facts) -> dict[str, str]:
    """The units the map names test, benchmark, example, docs or tooling code, with that role, when the project has
    a product unit with code of its own (a project of benchmarks alone is judged as it is)."""
    units = facts.of(Unit)
    if not any(unit.role == "product" and (unit.languages or unit.formats) for unit in units):
        return {}
    return {unit.directory: unit.role for unit in units if unit.role in AUXILIARY}


def _advised(result: Result, answer: object) -> Result:
    """A result that did not pass says which tools CI runs for the practice where they cannot fail the pipeline: they
    run, but enforce nothing (`continue-on-error`, `allow_failure`)."""
    if result.status is Status.PASS or not isinstance(answer, AdvisedTools):
        return result
    return result.with_details(*(_ADVISED.format(tool=tool, why=why) for tool, why in answer.advised()))


_ADVISED = "{tool} runs in CI but cannot fail it ({why})"


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
    roles = _auxiliary_roles(context.facts)
    for answer, named in found:
        result = _advised(judge(answer, allow_unknown=context.options.allow_unknown), answer)
        if role := roles.get(answer.unit):
            result = _warned(result, _AUXILIARY_UNIT.format(unit=answer.unit, role=role))
        results[(answer.language, answer.unit)] = _advisory(result, answer.language, named) if named else result
    none = "no unit of the project is written in these languages"
    merged, named_merged = _merged(results, auxiliary)
    folded = combined(merged, label=lambda place, kept: _label(place, kept, named_merged), none=none)
    units = dict.fromkeys(unit for _, unit in results)
    return replace(folded, places=tuple(_placed(unit, results, found, auxiliary) for unit in units))


def _merged(results: Mapping[_Place, Result], auxiliary: _Auxiliary) -> tuple[dict[_Place, Result], _Auxiliary]:
    """The results with the languages of one unit that have the same result (and the same auxiliary code) as one
    place (`JavaScript and TypeScript`), so that what they share is said once; and what named each place's code."""
    groups: dict[tuple[str, Result, tuple[str, ...]], list[str]] = {}
    for (language, unit), result in results.items():
        groups.setdefault((unit, result, auxiliary.get((language, unit), ())), []).append(language)
    places = {(" and ".join(languages), unit): (result, named) for (unit, result, named), languages in groups.items()}
    return {place: result for place, (result, _) in places.items()}, {
        place: named for place, (_, named) in places.items() if named
    }


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
