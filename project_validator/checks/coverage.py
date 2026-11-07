from project_validator.core import Check, Context, Result, Status
from project_validator.ecosystems import check_each_ecosystem, registered
from project_validator.ecosystems.model import labelled
from project_validator.facts.tools import built_in_tools
from project_validator.policy import judge_coverage
from project_validator.questions.coverage import language_coverage, measures_coverage


def _label(language: str, unit: str, languages: set[str], units: set[str]) -> str:
    """How a result is named among the others: by language, by unit, or by both, as far as they differ."""
    place = "the root" if unit == "." else unit
    if len(units) == 1:
        return language
    return place if len(languages) == 1 else f"{language} in {place}"


def _judge(languages: frozenset[str], context: Context) -> Result:
    """The coverage policy's judgement of each of `languages` the project uses, in each unit that has it; one result
    when they agree."""
    answers = [
        answer
        for language in sorted(languages & context.structure.languages)
        for answer in language_coverage(language, context.facts).units
    ]
    results = {
        (answer.language, answer.unit): judge_coverage(answer, allow_unknown=context.options.allow_unknown)
        for answer in answers
    }
    if not results:
        return Result(
            status=Status.SKIP, message="only the docs, tooling, examples or test fixtures use these languages"
        )
    if len(set(results.values())) == 1:
        return next(iter(results.values()))
    named = {language for language, _ in results}, {unit for _, unit in results}
    return labelled({_label(language, unit, *named): result for (language, unit), result in results.items()})


def _run(context: Context) -> Result:
    measured = coverage.languages
    judged = {ecosystem: ecosystem.languages & measured for ecosystem in registered() if ecosystem.languages & measured}
    return check_each_ecosystem(context, judged, _judge)


coverage = Check(
    name="coverage",
    description="CI reports branch coverage (or the finest the language's tools measure; path coverage is a bonus)",
    run=_run,
    languages=frozenset().union(*(tool.languages for tool in built_in_tools() if measures_coverage(tool))),
)
