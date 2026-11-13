"""JSON Schema: schemas (`*.schema.json`, or JSON whose top-level `$schema` names json-schema.org) and the documents
they describe, a format recognised by intent, never by plain `.json` files. The schemas are JSON, the Data format's,
so `data-wellformed` already covers one that does not parse. What is asked is that CI validates the documents against
the schemas (`schema-validation`: check-jsonschema, ajv, the `jsonschema` CLI, jv), that the schemas are formatted
(`code-formatting`: prettier, biome), that each names its dialect and `$id` (`schema-declared`; a dialect older than
2019-09 warns) and that CI checks the examples that come with the schemas (`schema-examples`: `ajv test` with
`--valid` and `--invalid`, or a validator run on an `examples` directory) and the schemas for breaking changes against
the main branch's (`schema-compatibility`: json-schema-diff)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.schema import (
    compatibility_checked,
    compatibility_checker,
    example_checker,
    examples_checked,
    names_examples,
    validated,
    validator,
)
from project_validator.facts.tools import Condition, Tool, all_of, any_of, combined, defined_by, starts, when
from project_validator.tools.prettier import prettier_tool

JSON_SCHEMA = "JSON Schema"
JSON_SCHEMA_ONLY = frozenset({JSON_SCHEMA})

_SCHEMA_NAME = re.compile(r"\.schema\.json$")
# A top-level `$schema` (indented once at most, or on the opening line); a nested one (a schema quoted inside another
# document) makes nothing.
_SCHEMA_DIALECT = re.compile(r'^(?:\{\s*)?\s{0,4}"\$schema"\s*:\s*"https?://json-schema\.org/', re.MULTILINE)


def json_schemas(project: Project) -> Iterator[str]:
    """The project's JSON Schemas: each `*.schema.json`, and each JSON file whose `$schema` is a JSON Schema dialect.
    A `$schema` naming another schema (a tool's configuration, a Compose file) is an instance, not a schema."""
    for path in project.files():
        name = PurePosixPath(path).name
        if _SCHEMA_NAME.search(name) or (name.endswith(".json") and _SCHEMA_DIALECT.search(project.read_head(path))):
            yield path


def json_schema_project(project: Project) -> frozenset[str]:
    """Whether the project holds JSON Schemas (see `json_schemas`)."""
    return JSON_SCHEMA_ONLY if next(json_schemas(project), None) is not None else frozenset()


JSON_SCHEMA_ECOSYSTEM = Ecosystem(
    label="JSON Schema",
    kind="format",
    languages=JSON_SCHEMA_ONLY,
    detect=json_schema_project,
    ci_programs=(("check-jsonschema",), ("ajv",), ("jsonschema",), ("jv",), ("json-schema-diff",)),
)


# --- Declaration ----------------------------------------------------------------------------------------------------

# The drafts before 2019-09, which the current dialects supersede.
_OLD_DRAFT = re.compile(r"draft-0[3467]\b")


def _read_schema(text: str) -> Declaration | None:
    """What a JSON Schema declares: its dialect (`$schema`) and its `$id` (`id`, in draft-04 and before). A schema
    that is not a JSON object, or does not parse, declares nothing that can be read."""
    try:
        schema = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(schema, dict):
        return None
    dialect = schema.get("$schema")
    old = _OLD_DRAFT.search(dialect) if isinstance(dialect, str) else None
    identifier = schema.get("$id", schema.get("id") if old else None)
    return declaring(
        {"$schema": dialect, "$id": identifier if isinstance(identifier, str) else None},
        outdated=f"{old[0]} is older than 2019-09" if old else None,
    )


JSON_SCHEMA_DECLARES = Declares(
    format=JSON_SCHEMA, what="dialect ($schema) and $id", find=json_schemas, read=_read_schema
)


# --- Validation -----------------------------------------------------------------------------------------------------


def _validator(name: str, how: str, validates: Condition, how_examples: str, checks: Condition) -> Tool:
    """A validator of the documents against the schemas, which checks the schemas' examples when run on them."""
    return combined(
        validator(name=name, languages=JSON_SCHEMA_ONLY, how=how, validates=when(validates, validated)),
        example_checker(name=name, languages=JSON_SCHEMA_ONLY, how=how_examples, checks=when(checks, examples_checked)),
    )


# A validator run on an `examples` directory checks the examples; `ajv test` asserts that each file is valid
# (`--valid`) or invalid (`--invalid`), which is what an example is for.
CHECK_JSONSCHEMA = _validator(
    "check-jsonschema",
    "check-jsonschema --schemafile <schema> <documents>",
    starts(("check-jsonschema",)),
    "check-jsonschema --schemafile <schema> examples/valid/*.json",
    all_of(starts(("check-jsonschema",)), names_examples),
)
# `ajv validate` and `ajv test` check documents; `ajv compile` only compiles the schema. npx runs the package as
# ajv-cli.
_AJV_TEST = starts(("ajv", "test"), ("ajv-cli", "test"))
_AJV_VALIDATE = starts(("ajv", "validate"), ("ajv-cli", "validate"))
AJV = _validator(
    "ajv",
    "ajv validate -s <schema> -d <documents> (ajv-cli)",
    any_of(_AJV_VALIDATE, _AJV_TEST),
    "ajv test -s <schema> -d 'examples/valid/*.json' --valid (and -d 'examples/invalid/*.json' --invalid)",
    any_of(_AJV_TEST, all_of(_AJV_VALIDATE, names_examples)),
)
JSONSCHEMA_CLI = _validator(
    "jsonschema",
    "jsonschema -i <document> <schema>",
    starts(("jsonschema",)),
    "jsonschema -i examples/valid/<document> <schema>",
    all_of(starts(("jsonschema",)), names_examples),
)
JV = _validator(
    "jv",
    "jv <schema> <documents>",
    starts(("jv",)),
    "jv <schema> examples/valid/*.json",
    all_of(starts(("jv",)), names_examples),
)


# --- Compatibility --------------------------------------------------------------------------------------------------

# json-schema-diff fails when the destination schema accepts less than the source: run against the main branch's copy
# of the schema (`git show origin/main:<schema>`).
JSON_SCHEMA_DIFF = compatibility_checker(
    name="json-schema-diff",
    languages=JSON_SCHEMA_ONLY,
    how="json-schema-diff <main branch's schema> <schema>",
    checks=when(starts(("json-schema-diff",)), compatibility_checked),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# prettier and biome format JSON; their configuration is the JavaScript profile's to read (`prettier`, `biome`).
PRETTIER = prettier_tool(JSON_SCHEMA_ONLY)
BIOME = format_tool(
    name="biome",
    languages=JSON_SCHEMA_ONLY,
    can={Enforcement.CHECK: "biome format . (or biome ci .)", Enforcement.APPLY: "biome format --write ."},
    formats=flagged(("biome", "format"), ("biome", "ci"), ("biome", "check"), applies=("--write", "--fix")),
    style=defined_by(files=("biome",)),
)
