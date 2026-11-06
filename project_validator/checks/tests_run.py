from project_validator.core import Context, Result, Status
from project_validator.ecosystems import practice
from project_validator.rules import TestSuite
from project_validator.text import matching_names


@practice(
    name="tests-run",
    description="Tests exist (registered with CTest or Meson for C/C++) and CI runs them",
    rule=TestSuite,
    aliases=("ctest-runs",),
)
def tests_run(suite: TestSuite, context: Context) -> Result:
    result = suite.found(context)
    if result.status != Status.PASS or matching_names(suite.texts(context), suite.runs):
        return result
    return Result.warned(f"{result.message}, but no CI configuration runs {suite.runner}", *result.details)
