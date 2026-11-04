import re
from collections.abc import Iterable

from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import SUGGESTED_LIZARD, FunctionLimits

# lizard options are case-sensitive (`-l` selects a language) and the default length limit of 1000 is no limit at all.
_LIZARD_LENGTH_LIMIT = re.compile(
    r"\blizard\b(?:\\\n|[^\n])*?(?<![\w-])"
    r"(?P<limit>(?:-L|--length|-T\s*(?:length|nloc)|--Threshold[\s=]+(?:length|nloc))[\s=]*\d+)"
)


def lizard_limits(texts: Iterable[str]) -> list[str]:
    found = (
        f"lizard {' '.join(match['limit'].split())}" for text in texts for match in _LIZARD_LENGTH_LIMIT.finditer(text)
    )
    return list(dict.fromkeys(found))


def _build_texts(context: Context) -> tuple[str, ...]:
    return (*context.ci_texts, *context.cmake_texts)


# lizard measures every ecosystem; an ecosystem's own way of limiting function length is judged when lizard is absent.
@practice(name="function-limits", description="Function length is limited by clang-tidy or lizard", rule=FunctionLimits)
def function_limits(rule: FunctionLimits, context: Context) -> Result:
    if found := lizard_limits(_build_texts(context)):
        return Result.passed(f"function length is limited with {', '.join(found)}")
    if rule.without_lizard is not None:
        return rule.without_lizard(context)
    return Result.failed(f"function length is never limited; run {SUGGESTED_LIZARD} in CI")
