"""Dynamically typed code is statically type checked, so type errors are found before the code runs."""

from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import TypeChecking
from project_validator.text import joined


@practice(
    name="type-checking",
    description="CI runs a static type checker on dynamically typed code (e.g. mypy, pyright), ideally strictly",
    rule=TypeChecking,
)
def type_checking(rule: TypeChecking, context: Context) -> Result:
    texts = rule.texts(context)
    running = [checker for checker in rule.checkers if checker.runs_in(texts)]
    if not running:
        if configured := [checker.not_running(context) for checker in rule.checkers if checker.configured(context)]:
            return Result.warned("; ".join(configured), rule.hint)
        return Result.failed("no type checker runs", rule.hint)
    ran = f"{joined([checker.named(context) for checker in running])} {'runs' if len(running) == 1 else 'run'}"
    if strict := rule.strict(context):
        return Result.passed(f"{ran}; strict mode bonus: {strict}")
    return Result.passed(ran, rule.strict_hint)
