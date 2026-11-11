"""No build output is committed: what the ignore rules keep out (see `vcs-ignore`) did not slip in before them."""

from __future__ import annotations

from project_validator.facts.outputs import known_build_outputs
from project_validator.judging import answered_check
from project_validator.policy.outputs import judge_committed
from project_validator.questions.outputs import committed_outputs


def output_languages() -> frozenset[str]:
    """The languages whose builds write a known build output."""
    return frozenset().union(*(output.languages for output in known_build_outputs()))


committed_artifacts = answered_check(
    name="committed-artifacts",
    description="No build outputs (e.g. object files, __pycache__/, target/) are committed",
    languages=output_languages,
    answers=committed_outputs,
    judge=judge_committed,
)
