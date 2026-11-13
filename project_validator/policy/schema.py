"""The schema validation policy: CI validates the documents against their schemas (a validator runs); none fails, as
a schema nothing is checked against guards nothing."""

from __future__ import annotations

from project_validator.facts.schema import VALIDATES
from project_validator.policy.tooling import required

judge_schema_validation = required(
    level=VALIDATES,
    impossible="no known tool validates {language} documents against their schemas",
    passed="CI validates the documents against their schemas with {tools}",
    asks="whether CI validates the documents against their schemas",
    missing="no schema validation found in CI configuration",
)

__all__ = ["judge_schema_validation"]
