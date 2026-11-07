from project_validator.facts.tools import known_tools
from project_validator.judging import answered_check
from project_validator.policy import judge_formatting
from project_validator.questions.formatting import formats, language_formatting

code_formatting = answered_check(
    name="code-formatting",
    description="Formatting is defined (e.g. .clang-format, ruff, rustfmt) and CI enforces it",
    languages=lambda: frozenset().union(*(tool.languages for tool in known_tools() if formats(tool))),
    answers=language_formatting,
    judge=lambda answer, allow_unknown: judge_formatting(answer, allow_unknown=allow_unknown),
)
