"""The schema aspects of tools (see `project_validator.facts.tools`): a run validates a format's documents against
their schemas (`schema`: check-jsonschema on JSON Schema instances, kubeconform on Kubernetes manifests, `helm lint
--strict` on a chart's values), or checks the examples that come with the schemas (`examples`: `ajv test` on the
valid and invalid examples, a linter whose rules validate a description's examples, a validator run on an `examples`
directory). Validators and example checkers are ordinary `Tool`s; `validator`, `validated`, `example_checker` and
`examples_checked` only spell them."""

from __future__ import annotations

import re
from collections.abc import Iterable

from project_validator.facts import Command, Setting, resolved
from project_validator.facts.tools import Claim, Run, Tool, provided

SCHEMA = "schema"
VALIDATES = "validates"
EXAMPLES = "examples"
CHECKED = "checked"

# A path component that names examples: `examples/valid/*.json`, `test/invalid_data.json`'s directory.
_EXAMPLE_PATH = re.compile(r"(?:^|/)(?:examples?|samples?|valid|invalid)(?:/|$)", re.IGNORECASE)


def validator(*, name: str, languages: frozenset[str], how: str, validates: Claim, reads: tuple[str, ...] = ()) -> Tool:
    """A validator of the documents of `languages` (formats, mostly) against their schemas: `how` to run it."""
    return Tool(name=name, languages=languages, can={SCHEMA: {VALIDATES: how}}, claims=validates, reads=reads)


def validated(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(SCHEMA, VALIDATES, read=read, heuristic=heuristic)


def example_checker(
    *, name: str, languages: frozenset[str], how: str, checks: Claim, reads: tuple[str, ...] = ()
) -> Tool:
    """A checker of the examples that come with the schemas of `languages`: `how` to run it."""
    return Tool(name=name, languages=languages, can={EXAMPLES: {CHECKED: how}}, claims=checks, reads=reads)


def examples_checked(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(EXAMPLES, CHECKED, read=read, heuristic=heuristic)


def names_examples(command: Command) -> bool:
    """Whether a command's arguments name an examples directory (`examples/valid/*.json`, `samples/`), as a validator
    run on the examples does."""
    return any(not word.startswith("-") and _EXAMPLE_PATH.search(word) for word in resolved(command)[1:])


__all__ = [
    "CHECKED",
    "EXAMPLES",
    "SCHEMA",
    "VALIDATES",
    "example_checker",
    "examples_checked",
    "names_examples",
    "validated",
    "validator",
]
