"""The pinning policy: every reusable step is pinned to a full commit, so a moved tag or a pushed branch cannot change
it; with `allow_official_tags`, GitHub's own actions may be pinned to tags."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.questions import Answer
from project_validator.questions.pinning import BRANCH, TAG, UNPINNED, PinningAnswer

HINT = (
    "pin each action to the full commit of its release, e.g. actions/checkout@<40-character SHA> # v4.2.2; "
    "Dependabot and Renovate keep such pins up to date"
)


def judge_pinning(answer: PinningAnswer, *, allow_unknown: bool = False, allow_official_tags: bool = False) -> Result:
    """Unpinned or branch-following references fail; tags warn (unless allowed for official actions); none loose
    passes. Nothing here is ever unknown: a reference is read from the file as written."""
    del allow_unknown
    if answer.answer is Answer.IMPOSSIBLE:
        return Result.skipped("no CI configuration with reusable steps")
    loose = [found for found in answer.loose() if not (allow_official_tags and found.how == TAG and found.official)]
    listed = [f"{found.path}: {found.reference} ({found.how})" for found in loose]
    count = len(answer.references)
    if any(found.how in (UNPINNED, BRANCH) for found in loose):
        return Result.failed(f"{len(loose)} of {count} actions are not pinned to a commit", *listed, HINT)
    if loose:
        return Result.warned(f"{len(loose)} of {count} actions are pinned to a tag rather than a commit", *listed, HINT)
    if not count:
        return Result.passed("CI uses no actions from other repositories")
    return Result.passed(
        "1 action is pinned to a commit" if count == 1 else f"all {count} actions are pinned to a commit"
    )


__all__ = ["HINT", "judge_pinning"]
