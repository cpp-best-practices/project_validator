"""The link-check question: for each documentation site's format, in each unit of the project that has it, does CI
check the site's links and fail on a broken one?"""

from __future__ import annotations

from project_validator.facts.links import CHECKED, LINKS
from project_validator.questions import EVERY_KIND, Question
from project_validator.questions.tooling import aspect_answers

link_check = aspect_answers(LINKS, CHECKED)
LINK_CHECK_QUESTION = Question(
    name="link-check",
    description="Does CI check the links of each documentation site in each unit?",
    answer=link_check,
    kinds=EVERY_KIND,
)

__all__ = ["LINK_CHECK_QUESTION", "link_check"]
