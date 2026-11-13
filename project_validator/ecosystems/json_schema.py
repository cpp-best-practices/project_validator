"""JSON Schema: schemas (`*.schema.json`, or JSON whose top-level `$schema` names json-schema.org) and the documents
they describe, a format recognised by intent, never by plain `.json` files. The schemas are JSON, the Data format's,
so `data-wellformed` already covers one that does not parse. What is asked is that CI validates the documents against
the schemas (`schema-validation`: check-jsonschema, ajv, the `jsonschema` CLI, jv), that the schemas are formatted
(`code-formatting`: prettier, biome) and that each names its dialect and `$id` (`schema-declared`; a dialect older
than 2019-09 warns). Whether the schemas come with examples CI checks and are diffed for breaking changes are the
other schema practices of #85, not yet built."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.schema import validated, validator
from project_validator.facts.tools import defined_by, starts, when
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
    ci_programs=(("check-jsonschema",), ("ajv",), ("jsonschema",), ("jv",)),
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

CHECK_JSONSCHEMA = validator(
    name="check-jsonschema",
    languages=JSON_SCHEMA_ONLY,
    how="check-jsonschema --schemafile <schema> <documents>",
    validates=when(starts(("check-jsonschema",)), validated),
)
# `ajv validate` and `ajv test` check documents; `ajv compile` only compiles the schema. npx runs the package as
# ajv-cli.
AJV = validator(
    name="ajv",
    languages=JSON_SCHEMA_ONLY,
    how="ajv validate -s <schema> -d <documents> (ajv-cli)",
    validates=when(
        starts(("ajv", "validate"), ("ajv", "test"), ("ajv-cli", "validate"), ("ajv-cli", "test")), validated
    ),
)
JSONSCHEMA_CLI = validator(
    name="jsonschema",
    languages=JSON_SCHEMA_ONLY,
    how="jsonschema -i <document> <schema>",
    validates=when(starts(("jsonschema",)), validated),
)
JV = validator(
    name="jv",
    languages=JSON_SCHEMA_ONLY,
    how="jv <schema> <documents>",
    validates=when(starts(("jv",)), validated),
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
