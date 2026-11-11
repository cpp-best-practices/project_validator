"""CI lints its own configuration, so a broken or unsafe pipeline is caught before it runs."""

from __future__ import annotations

from project_validator.core import Context, Result, check
from project_validator.policy.ci_lint import judge_ci_lint
from project_validator.questions.ci_lint import ci_lint_answer


@check(name="ci-lint", description="CI lints its own configuration (e.g. actionlint or zizmor)")
def ci_lint(context: Context) -> Result:
    return judge_ci_lint(ci_lint_answer(context.facts))
