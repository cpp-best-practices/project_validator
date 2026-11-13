"""Tabular data: Frictionless Data Packages (`datapackage.json`, or `.yaml`), Table Schemas and the CSV tables they
describe, a format recognised by intent: the descriptor's name, or a JSON or YAML file whose `$schema` or `profile`
names a Data Package profile (datapackage.org, frictionlessdata.io). The descriptors stay JSON or YAML, the Data
format's, so `data-wellformed` already covers one that does not parse; the tables (`.csv`, `.tsv`) are data, never
sources. What is asked is that CI validates the tables against their
schemas (`schema-validation`: `frictionless validate`, or its action; csvlint with a schema; goodtables, its
predecessor). A `dvc.yaml` alone shows data versioning, not a schema to validate against, and `large-files` already
honours DVC, so it recognises nothing here. The other schema practices of #85 are not yet built."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.expansion import Action
from project_validator.facts.schema import validated, validator
from project_validator.facts.tools import all_of, starts, when, with_option

DATA_PACKAGE = "Data Package"
DATA_PACKAGE_ONLY = frozenset({DATA_PACKAGE})

_DESCRIPTOR_NAMES = frozenset(
    {"datapackage.json", "datapackage.yaml", "datapackage.yml", "tableschema.json", "tableschema.yaml"}
)
_DESCRIPTOR_SUFFIXES = (".json", ".yaml", ".yml")
# `"$schema": "https://datapackage.org/profiles/2.0/datapackage.json"` (version 2), or `"profile":
# "tabular-data-package"` or a specs.frictionlessdata.io URL (version 1), in JSON or YAML.
_PROFILE = re.compile(
    r"[\"']?(?:\$schema|profile)[\"']?\s*:\s*[\"']?(?:https?://(?:specs\.)?(?:datapackage\.org|frictionlessdata\.io)/"
    r"|(?:tabular-)?data-(?:package|resource)\b|table-schema\b)"
)


def data_package_project(project: Project) -> frozenset[str]:
    """Whether the project holds Data Package descriptors: a `datapackage.json` (or `.yaml`, or a `tableschema.json`),
    or a JSON or YAML file whose `$schema` or `profile` names a Data Package profile. A CSV alone is a table of no
    declared schema."""
    for path in project.files():
        name = PurePosixPath(path).name
        if name in _DESCRIPTOR_NAMES:
            return DATA_PACKAGE_ONLY
        if name.endswith(_DESCRIPTOR_SUFFIXES) and _PROFILE.search(project.read_head(path)):
            return DATA_PACKAGE_ONLY
    return frozenset()


TABULAR_DATA_ECOSYSTEM = Ecosystem(
    label="Tabular data",
    kind="format",
    languages=DATA_PACKAGE_ONLY,
    detect=data_package_project,
    ci_programs=(("frictionless",), ("goodtables",), ("csvlint",)),
    ci_usage=re.compile(r"(?<![\w-])frictionlessdata/(?:frictionless-ci|repository)\b"),
)


# --- Validation -----------------------------------------------------------------------------------------------------

# `frictionless validate` infers what it is given (a package, a resource, a table with `--schema`) and validates the
# tables against the schemas; `describe` and `extract` only read them.
FRICTIONLESS = validator(
    name="frictionless",
    languages=DATA_PACKAGE_ONLY,
    how="frictionless validate datapackage.json (or frictionlessdata/frictionless-ci)",
    validates=when(starts(("frictionless", "validate")), validated),
)
GOODTABLES = validator(
    name="goodtables",
    languages=DATA_PACKAGE_ONLY,
    how="goodtables validate datapackage.json",
    validates=when(starts(("goodtables", "validate")), validated),
)
# Without `--schema`, csvlint checks that a CSV is well formed, against no schema.
CSVLINT = validator(
    name="csvlint",
    languages=DATA_PACKAGE_ONLY,
    how="csvlint --schema=<table schema> <table>",
    validates=when(all_of(starts(("csvlint",)), with_option("--schema", "-s")), validated),
)


def _frictionless_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`frictionlessdata/frictionless-ci` (once `frictionlessdata/repository`) validates an inquiry, or the packages,
    resources or tables its globs name; told nothing, the data packages of the repository."""
    sources = [inputs[name] for name in ("inquiry", "packages", "resources", "tables") if inputs.get(name)]
    return (("frictionless", "validate", *(sources or ["datapackage.json"])),)


FRICTIONLESS_CI = Action(name="frictionlessdata/frictionless-ci", runs=_frictionless_action)
FRICTIONLESS_REPOSITORY = Action(name="frictionlessdata/repository", runs=_frictionless_action)
