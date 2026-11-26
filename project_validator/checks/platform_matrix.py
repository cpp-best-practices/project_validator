"""CI runs on several operating systems with several compilers (or interpreter and toolchain versions)."""

from __future__ import annotations

from dataclasses import replace

from project_validator.facts.axes import handled
from project_validator.judging import answered_check
from project_validator.policy.platforms import judge_matrix
from project_validator.questions.platforms import platform_answers

# Only CI can satisfy it: judged at an entry level without CI (upstream #384).
platform_matrix = replace(
    answered_check(
        name="platform-matrix",
        description="CI runs on several operating systems with several compilers (or interpreter/toolchain versions)",
        languages=handled(),
        answers=platform_answers,
        judge=judge_matrix,
    ),
    ci_only=True,
)
