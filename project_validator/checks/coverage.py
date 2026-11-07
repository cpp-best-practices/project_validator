from project_validator.core import Check, Context, Result
from project_validator.ecosystems import check_each_ecosystem, registered
from project_validator.ecosystems.model import labelled
from project_validator.facts.coverage import built_in_coverage_tools
from project_validator.policy import judge_coverage
from project_validator.questions.coverage import coverage_answer


def _judge(languages: frozenset[str], context: Context) -> Result:
    """The coverage policy's judgement of each of `languages` the project uses, one result when they agree."""
    tools = built_in_coverage_tools()
    results = {
        language: judge_coverage(
            coverage_answer(language, context.facts, tools), allow_unknown=context.options.allow_unknown
        )
        for language in sorted(languages & context.structure.languages)
    }
    if len(set(results.values())) == 1:
        return next(iter(results.values()))
    return labelled(results)


def _run(context: Context) -> Result:
    measured = coverage.languages
    judged = {ecosystem: ecosystem.languages & measured for ecosystem in registered() if ecosystem.languages & measured}
    return check_each_ecosystem(context, judged, _judge)


coverage = Check(
    name="coverage",
    description="CI reports branch coverage (or the finest the language's tools measure; path coverage is a bonus)",
    run=_run,
    languages=frozenset().union(*(tool.languages for tool in built_in_coverage_tools())),
)
