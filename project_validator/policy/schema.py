"""The schema policies: CI validates the documents against their schemas (a validator runs); none fails, as a schema
nothing is checked against guards nothing. CI checks the examples that come with the schemas (valid ones that must
pass, invalid ones that must fail); none warns, as examples are a schema's tests and a schema may do without."""

from __future__ import annotations

from project_validator.facts.schema import CHECKED, VALIDATES
from project_validator.policy.tooling import advised, required

judge_schema_validation = required(
    level=VALIDATES,
    impossible="no known tool validates {language} documents against their schemas",
    passed="CI validates the documents against their schemas with {tools}",
    asks="whether CI validates the documents against their schemas",
    missing="no schema validation found in CI configuration",
)

judge_schema_examples = advised(
    level=CHECKED,
    impossible="no known tool checks the examples of {language} schemas",
    passed="CI checks the schemas' examples with {tools}",
    asks="whether CI checks the schemas' examples",
    missing="no check of the schemas' examples found in CI configuration",
)

__all__ = ["judge_schema_examples", "judge_schema_validation"]
