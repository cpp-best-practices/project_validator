"""CI validates each format's documents against their schemas: JSON Schema instances with check-jsonschema or ajv,
Kubernetes manifests with kubeconform."""

from __future__ import annotations

from project_validator.facts.schema import SCHEMA
from project_validator.judging import answered_check
from project_validator.policy.schema import judge_schema_validation
from project_validator.questions.schema import schema_validation as schema_answers

schema_validation = answered_check(
    name="schema-validation",
    description="CI validates each format's documents in each unit against their schemas (check-jsonschema, ajv, "
    "kubeconform, helm lint --strict)",
    aspect=SCHEMA,
    answers=schema_answers,
    judge=judge_schema_validation,
)
