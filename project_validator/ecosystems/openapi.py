"""OpenAPI and AsyncAPI descriptions, two formats recognised by intent: a YAML or JSON file whose top-level key is
`openapi` (or `swagger`, the 2.0 name) or `asyncapi`. The files stay YAML or JSON, the Data format's. What is asked is
that CI lints the description against its specification (`schema-validation`, and `static-analysis` for the same
run: spectral with a ruleset, redocly, vacuum, swagger-cli, openapi-generator's validate; the AsyncAPI CLI). The other
schema practices of #85 (the version declared, the examples checked or contract-tested with schemathesis or dredd,
breaking changes with oasdiff) are not yet built."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.schema import validated, validator
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import Condition, Definition, Tool, combined, defined_by, starts, when

OPENAPI, ASYNCAPI = "OpenAPI", "AsyncAPI"
OPENAPI_ONLY, ASYNCAPI_ONLY = frozenset({OPENAPI}), frozenset({ASYNCAPI})
API_FORMATS = OPENAPI_ONLY | ASYNCAPI_ONLY

# The top-level key, in YAML (`openapi: 3.1.0`, at the first column) or JSON (`"openapi": "3.1.0"`, indented once).
_DESCRIBES = {
    OPENAPI: re.compile(r"^(?:openapi|swagger)\s*:|^\s{0,4}\"(?:openapi|swagger)\"\s*:", re.MULTILINE),
    ASYNCAPI: re.compile(r"^asyncapi\s*:|^\s{0,4}\"asyncapi\"\s*:", re.MULTILINE),
}
_DESCRIPTION_SUFFIXES = (".yaml", ".yml", ".json")


def api_descriptions(project: Project) -> frozenset[str]:
    """The API description formats among the project's YAML and JSON files, told by their top-level key."""
    found: set[str] = set()
    for path in project.files():
        if PurePosixPath(path).suffix not in _DESCRIPTION_SUFFIXES:
            continue
        head = project.read_head(path)
        found.update(name for name, key in _DESCRIBES.items() if key.search(head))
        if found == API_FORMATS:
            break
    return frozenset(found)


API_ECOSYSTEM = Ecosystem(
    label="OpenAPI/AsyncAPI",
    kind="format",
    languages=API_FORMATS,
    detect=api_descriptions,
    ci_programs=(("spectral",), ("spectral-cli",), ("redocly",), ("vacuum",), ("swagger-cli",), ("asyncapi",)),
    ci_usage=re.compile(r"(?<![\w-])spectral-action\b"),
)


def _linter(name: str, languages: frozenset[str], how: str, runs: Condition, rules: Definition | None = None) -> Tool:
    """A linter of API descriptions, which validates them against the specification and lints them at once."""
    return combined(
        validator(name=name, languages=languages, how=how, validates=when(runs, validated)),
        analyzer(name=name, languages=languages, how=how, analyses=when(runs, analysed), rules=rules),
    )


SPECTRAL_SETTINGS = file_reader(
    "spectral", (".spectral.yaml", ".spectral.yml", ".spectral.json", ".spectral.js", ".spectral.mjs", ".spectral.cjs")
)
# spectral does nothing without a ruleset (`extends: spectral:oas`); npx runs the package as spectral-cli.
SPECTRAL = _linter(
    "spectral",
    API_FORMATS,
    "spectral lint <description> (with a .spectral.yaml ruleset; or stoplightio/spectral-action)",
    starts(("spectral", "lint"), ("spectral-cli", "lint")),
    defined_by(files=(SPECTRAL_SETTINGS.name,), default=False),
)
REDOCLY_SETTINGS = file_reader("redocly", ("redocly.yaml", ".redocly.yaml", "redocly.yml", ".redocly.yml"))
REDOCLY = _linter(
    "redocly",
    OPENAPI_ONLY,
    "redocly lint <description>",
    starts(("redocly", "lint"), ("openapi", "lint")),
    defined_by(files=(REDOCLY_SETTINGS.name,)),
)
VACUUM = _linter("vacuum", OPENAPI_ONLY, "vacuum lint <description>", starts(("vacuum", "lint")))
SWAGGER_CLI = _linter(
    "swagger-cli", OPENAPI_ONLY, "swagger-cli validate <description>", starts(("swagger-cli", "validate"))
)
OPENAPI_GENERATOR = _linter(
    "openapi-generator",
    OPENAPI_ONLY,
    "openapi-generator-cli validate -i <description>",
    starts(("openapi-generator", "validate"), ("openapi-generator-cli", "validate")),
)
ASYNCAPI_CLI = _linter("asyncapi", ASYNCAPI_ONLY, "asyncapi validate <description>", starts(("asyncapi", "validate")))

SPECTRAL_ACTION = Action(
    name="stoplightio/spectral-action",
    runs=lambda inputs: (("spectral", "lint", *inputs.get("file_glob", "*.yaml").split()),),
)
