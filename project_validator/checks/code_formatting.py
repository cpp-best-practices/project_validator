from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import Formatter
from project_validator.text import matching_names


@practice(
    name="code-formatting",
    description="Formatting is defined (e.g. .clang-format, ruff, rustfmt) and CI enforces it",
    rule=Formatter,
)
def code_formatting(formatter: Formatter, context: Context) -> Result:
    config = formatter.config_file(context)
    tools = matching_names(formatter.texts(context), formatter.runs)
    if tools and config is not None:
        return Result.passed(f"{config} is defined and CI runs {', '.join(tools)}")
    if tools and formatter.default_style:
        return Result.passed(f"CI enforces the {', '.join(tools)} style")
    if config is None and formatter.default_style:
        return Result.failed(f"CI never runs {formatter.name}; its formatting is not enforced", formatter.hint)
    if config is None:
        return Result.failed(f"no {formatter.name} configuration found; formatting is not defined", formatter.hint)
    return Result.warned(f"{config} is defined but CI does not run {formatter.name}", formatter.hint)
