"""Tests and developer-only settings are conditioned on the project being built on its own (PROJECT_IS_TOP_LEVEL;
Meson's meson.is_subproject()), so that it works as a subproject through FetchContent, CPM or add_subdirectory."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import top_level_guard_answers

top_level_guard = answered_check(
    name=PracticeName.TOP_LEVEL_GUARD,
    description="Tests and developer-only settings are guarded by PROJECT_IS_TOP_LEVEL (Meson: "
    "meson.is_subproject()), so the project works as a subproject",
    languages=handled(PracticeName.TOP_LEVEL_GUARD),
    answers=top_level_guard_answers,
    judge=judge_any_one,
)
