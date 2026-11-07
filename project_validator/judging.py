"""Checks made of a question and its policy: each language the project uses is judged in each unit that has it, and
the results are named by language, by unit, or by both, as far as they differ."""

from collections.abc import Callable

from project_validator.core import Check, Context, Result, Status
from project_validator.ecosystems import check_each_ecosystem, registered
from project_validator.ecosystems.model import labelled
from project_validator.facts import Facts
from project_validator.questions import LanguageAnswers, UnitAnswer

type Judge[A] = Callable[[A, bool], Result]


def _label(language: str, unit: str, languages: set[str], units: set[str]) -> str:
    """How a result is named among the others: by language, by unit, or by both, as far as they differ."""
    place = "the root" if unit == "." else unit
    if len(units) == 1:
        return language
    return place if len(languages) == 1 else f"{language} in {place}"


def judged[A: UnitAnswer](
    languages: frozenset[str],
    context: Context,
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
) -> Result:
    """The policy's judgement of each of `languages` the project uses, in each unit that has it; one result when they
    agree."""
    found = [
        answer
        for language in sorted(languages & context.structure.languages)
        for answer in answers(language, context.facts).units
    ]
    results = {(answer.language, answer.unit): judge(answer, context.options.allow_unknown) for answer in found}
    if not results:
        return Result(
            status=Status.SKIP, message="only the docs, tooling, examples or test fixtures use these languages"
        )
    if len(set(results.values())) == 1:
        return next(iter(results.values()))
    named = {language for language, _ in results}, {unit for _, unit in results}
    return labelled({_label(language, unit, *named): result for (language, unit), result in results.items()})


def answered_check[A: UnitAnswer](
    *,
    name: str,
    description: str,
    languages: Callable[[], frozenset[str]],
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
    aliases: tuple[str, ...] = (),
) -> Check:
    """A check that judges a question's answers by a policy, for each ecosystem the project uses (its findings
    labelled by ecosystem as other checks' are). It applies to the `languages` its known tools handle."""

    def run(context: Context) -> Result:
        handled = languages()
        by_ecosystem = {
            ecosystem: ecosystem.languages & handled for ecosystem in registered() if ecosystem.languages & handled
        }
        return check_each_ecosystem(
            context, by_ecosystem, lambda judged_languages, found: judged(judged_languages, found, answers, judge)
        )

    return Check(
        name=name, description=description, run=run, languages=languages(), languages_from=languages, aliases=aliases
    )


__all__ = ["answered_check", "judged"]
