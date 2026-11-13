"""The static analysis and type checking questions: for each language, in each unit of the project that has it, does
CI run its static analyzers (with the checks the project defines) and type checkers (strictly, as a bonus)?"""

from __future__ import annotations

from project_validator.facts.analysis import ANALYSIS, CHECKS, TYPE_CHECK, Strictness
from project_validator.questions import EVERY_KIND, Question
from project_validator.questions.tooling import aspect_answers

static_analysis = aspect_answers(ANALYSIS, CHECKS)
type_checking = aspect_answers(TYPE_CHECK, Strictness.CHECKS)

STATIC_ANALYSIS_QUESTION = Question(
    name="static-analysis",
    description="Does CI run static analyzers on each language in each unit, and where are their checks defined?",
    answer=static_analysis,
    kinds=EVERY_KIND,
)
TYPE_CHECKING_QUESTION = Question(
    name="type-checking",
    description="Does CI type check each language in each unit, and does it do so strictly?",
    answer=type_checking,
)

__all__ = ["STATIC_ANALYSIS_QUESTION", "TYPE_CHECKING_QUESTION", "static_analysis", "type_checking"]
