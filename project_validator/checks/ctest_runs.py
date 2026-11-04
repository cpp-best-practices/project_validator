from project_validator.core import Context, Result, Status
from project_validator.ecosystems import practice
from project_validator.rules import TestSuite
from project_validator.text import matching_names


@practice(
    name="ctest-runs",
    description="Tests exist (registered with CTest for C/C++) and CI runs them",
    rule=TestSuite,
)
def ctest_runs(suite: TestSuite, context: Context) -> Result:
    result = suite.found(context)
    if result.status != Status.PASS or matching_names(context.ci_texts, suite.runs):
        return result
    return Result.warned(f"{result.message}, but no CI configuration runs {suite.runner}", *result.details)
