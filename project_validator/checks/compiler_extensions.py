"""Code is compiled as standardised, without the compilers' extensions: -std=c++NN rather than -std=gnu++NN for C++,
-std=cNN rather than -std=gnuNN for C, a standard -std= for Fortran."""

from __future__ import annotations

from project_validator.facts.practices import PracticeName, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import practice_answers

compiler_extensions = answered_check(
    name=PracticeName.EXTENSIONS,
    description="Compiler extensions are disabled (-std=c++NN or -std=cNN rather than -std=gnu++NN or -std=gnuNN)",
    languages=handled(PracticeName.EXTENSIONS),
    answers=practice_answers(PracticeName.EXTENSIONS),
    judge=judge_any_one,
    aliases=("cxx-extensions",),
)
