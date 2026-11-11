"""The dependency audit question: for each language, in each unit of the project that has it, does CI check the
dependencies against known vulnerabilities?"""

from __future__ import annotations

from project_validator.facts.audit import AUDIT, RUNS
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

dependency_audit = aspect_answers(AUDIT, RUNS)
DEPENDENCY_AUDIT_QUESTION = Question(
    name="dependency-audit",
    description="Does CI check each language's dependencies in each unit against known vulnerabilities?",
    answer=dependency_audit,
)

__all__ = ["DEPENDENCY_AUDIT_QUESTION", "dependency_audit"]
