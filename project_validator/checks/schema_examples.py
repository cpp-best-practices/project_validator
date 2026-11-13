"""CI checks the examples that come with each format's schemas: valid examples that must pass and invalid ones that
must fail (`ajv test --valid`, `--invalid`), a validator run on an `examples` directory, a linter whose rules validate
a description's examples (spectral, redocly, vacuum), or contract tests (schemathesis, dredd)."""

from __future__ import annotations

from project_validator.facts.schema import EXAMPLES
from project_validator.judging import answered_check
from project_validator.policy.schema import judge_schema_examples
from project_validator.questions.schema import schema_examples as example_answers

schema_examples = answered_check(
    name="schema-examples",
    description="CI checks the examples that come with each format's schemas in each unit: valid ones that must "
    "pass and invalid ones that must fail (ajv test, a validator run on examples/, spectral, schemathesis)",
    aspect=EXAMPLES,
    answers=example_answers,
    judge=judge_schema_examples,
)
