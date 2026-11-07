"""The function length question: for each language, in each unit of the project that has it, does CI limit how long
its functions may be?"""

from project_validator.facts.limits import FUNCTION_LENGTH, LIMITS
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

function_limits = aspect_answers(FUNCTION_LENGTH, LIMITS)
FUNCTION_LIMITS_QUESTION = Question(
    name="function-limits",
    description="Does CI limit the length of each language's functions in each unit?",
    answer=function_limits,
)

__all__ = ["FUNCTION_LIMITS_QUESTION", "function_limits"]
