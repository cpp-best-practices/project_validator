"""In-source builds are prevented: a CMake file compares the source and binary directories and stops when they are
equal, or CMAKE_DISABLE_IN_SOURCE_BUILD is set; Meson builds out of source by itself."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import out_of_source_answers

out_of_source_build = answered_check(
    name=PracticeName.OUT_OF_SOURCE,
    description="The build prevents in-source builds (CMAKE_SOURCE_DIR compared with CMAKE_BINARY_DIR; Meson "
    "always does)",
    languages=handled(PracticeName.OUT_OF_SOURCE),
    answers=out_of_source_answers,
    judge=judge_any_one,
)
