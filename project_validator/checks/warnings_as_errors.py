from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import WarningsAsErrors
from project_validator.text import matching_names


@practice(
    name="warnings-as-errors",
    description="Compiler warnings are treated as errors in at least one configuration",
    rule=WarningsAsErrors,
)
def warnings_as_errors(rule: WarningsAsErrors, context: Context) -> Result:
    if flags := matching_names(rule.texts(context), rule.flags):
        return Result.passed(f"warnings are treated as errors with {', '.join(flags)}")
    return Result.failed(f"warnings are not treated as errors in {rule.searched}", rule.hint)
