"""C and C++ are compiled as standardised, without the compilers' extensions (-std=c++NN rather than -std=gnu++NN)."""

from project_validator.facts.practices import EXTENSIONS, handled
from project_validator.judging import answered_check
from project_validator.policy.practices import judge_any_one
from project_validator.questions.practices import practice_answers

cxx_extensions = answered_check(
    name=EXTENSIONS,
    description="Compiler extensions are disabled (-std=c++NN rather than -std=gnu++NN)",
    languages=handled(EXTENSIONS),
    answers=practice_answers(EXTENSIONS),
    judge=lambda answer, allow_unknown: judge_any_one(answer, allow_unknown=allow_unknown),
)
