from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import CoverageTools
from project_validator.text import matching_names


@practice(name="coverage", description="CI reports branch coverage (path coverage is a bonus)", rule=CoverageTools)
def coverage(tools: CoverageTools, context: Context) -> Result:
    texts = tools.texts(context)
    branch_tools = matching_names(texts, tools.branch)
    if not branch_tools:
        return Result.failed(f"no branch coverage reporting found in {tools.searched}")

    message = f"branch coverage is reported with {', '.join(branch_tools)}"
    if path_tools := matching_names(texts, tools.path):
        return Result.passed(f"{message}; path coverage bonus: {', '.join(path_tools)}")
    return Result.passed(message, *([tools.path_hint] if tools.path_hint else []))
