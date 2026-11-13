"""Every schema declares what it is: its dialect (`$schema`, an `openapi` version, a `.proto` file's `syntax`) and
its identifier (`$id`, `targetNamespace`, `package`), so that it is read as meant and can be referred to. Judged per
format (the registry's formats whose schemas declare themselves) in each unit of the project whose files are in
it."""

from __future__ import annotations

from project_validator.facts.declaration import declared_formats
from project_validator.judging import answered_check
from project_validator.policy.declaration import judge_schema_declared
from project_validator.questions.declaration import schema_declarations

schema_declared = answered_check(
    name="schema-declared",
    description="Every schema declares its dialect and its identifier ($schema and $id, an openapi version and "
    "info.version, a targetNamespace, a syntax and package); a superseded dialect warns",
    languages=declared_formats,
    answers=schema_declarations,
    judge=judge_schema_declared,
)
