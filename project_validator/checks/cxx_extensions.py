"""C and C++ are compiled as standardised, without the compilers' extensions (-std=c++NN rather than -std=gnu++NN)."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import practice_answers

cxx_extensions = answered_check(
    name=PracticeName.EXTENSIONS,
    description="Compiler extensions are disabled (-std=c++NN rather than -std=gnu++NN)",
    languages=handled(PracticeName.EXTENSIONS),
    answers=practice_answers(PracticeName.EXTENSIONS),
    judge=judge_any_one,
)
