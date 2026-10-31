from project_validator.core import Context, Result, check
from project_validator.text import matching_names, pattern

CONFIG_FILES = (".clang-format", "_clang-format")

RUNS_CLANG_FORMAT = (pattern("clang-format", r"(?<![\w.-])clang-format\b"),)


@check(name="clang-format", description="Formatting is defined with .clang-format and CI enforces it")
def clang_format(context: Context) -> Result:
    config = next((name for name in CONFIG_FILES if context.project.exists(name)), None)
    if config is None:
        return Result.failed("no .clang-format file found; formatting is not defined")
    if matching_names(context.ci_texts, RUNS_CLANG_FORMAT):
        return Result.passed(f"{config} is defined and CI runs clang-format")
    return Result.warned(
        f"{config} is defined but CI does not run clang-format",
        "consider a CI job that checks formatting (clang-format --dry-run -Werror) or applies it automatically",
    )
