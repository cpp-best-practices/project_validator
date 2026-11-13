"""The schema validation aspect of tools (see `project_validator.facts.tools`): a run validates a format's documents
against their schemas (check-jsonschema on JSON Schema instances, kubeconform on Kubernetes manifests, `helm lint
--strict` on a chart's values). Validators are ordinary `Tool`s; `validator` and `validated` only spell them."""

from __future__ import annotations

from collections.abc import Iterable

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Run, Tool, provided

SCHEMA = "schema"
VALIDATES = "validates"


def validator(*, name: str, languages: frozenset[str], how: str, validates: Claim, reads: tuple[str, ...] = ()) -> Tool:
    """A validator of the documents of `languages` (formats, mostly) against their schemas: `how` to run it."""
    return Tool(name=name, languages=languages, can={SCHEMA: {VALIDATES: how}}, claims=validates, reads=reads)


def validated(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(SCHEMA, VALIDATES, read=read, heuristic=heuristic)


__all__ = ["SCHEMA", "VALIDATES", "validated", "validator"]
