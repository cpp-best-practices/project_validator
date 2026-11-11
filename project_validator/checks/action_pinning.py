"""The reusable CI steps a project runs are pinned to commits, so a moved tag or a pushed branch cannot change them."""

from __future__ import annotations

from project_validator.core import Context, Result, check
from project_validator.policy.pinning import judge_pinning
from project_validator.questions.pinning import pinning_answer


@check(name="action-pinning", description="The actions CI uses are pinned to full commit SHAs")
def action_pinning(context: Context) -> Result:
    return judge_pinning(pinning_answer(context.facts), allow_official_tags=context.options.allow_official_tags)
