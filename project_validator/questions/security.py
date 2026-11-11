"""The code security scanning question: for each language, in each unit of the project that has it, does CI scan the
code for security problems?"""

from __future__ import annotations

from project_validator.facts.security import SCANS, SECURITY
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

security_scanning = aspect_answers(SECURITY, SCANS)
SECURITY_SCANNING_QUESTION = Question(
    name="security-scanning",
    description="Does CI scan each language's code in each unit for security problems?",
    answer=security_scanning,
)

__all__ = ["SECURITY_SCANNING_QUESTION", "security_scanning"]
