"""CI checks each format's schemas for breaking changes against what was published before (the main branch, a
registry): `buf breaking`, `oasdiff breaking`, json-schema-diff. A schema is a contract; a change that breaks its
consumers should be seen before it is merged."""

from __future__ import annotations

from project_validator.facts.schema import COMPATIBILITY
from project_validator.judging import answered_check
from project_validator.policy.schema import judge_schema_compatibility
from project_validator.questions.schema import schema_compatibility as compatibility_answers

schema_compatibility = answered_check(
    name="schema-compatibility",
    description="CI checks each format's schemas in each unit for breaking changes against the main branch or a "
    "registry (buf breaking, oasdiff breaking, json-schema-diff)",
    aspect=COMPATIBILITY,
    answers=compatibility_answers,
    judge=judge_schema_compatibility,
)
