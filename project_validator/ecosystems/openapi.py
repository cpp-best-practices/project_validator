"""OpenAPI and AsyncAPI descriptions, two formats recognised by intent: a YAML or JSON file whose top-level key is
`openapi` (or `swagger`, the 2.0 name) or `asyncapi`. The files stay YAML or JSON, the Data format's. What is asked is
that CI lints the description against its specification (`schema-validation`, and `static-analysis` for the same
run: spectral with a ruleset, redocly, vacuum, swagger-cli, openapi-generator's validate; the AsyncAPI CLI), and that
each description declares its version and `info.version` (`schema-declared`; Swagger 2.0 warns), and that the
description's examples are checked (`schema-examples`: spectral's, redocly's and vacuum's rules validate them; or
contract tests with schemathesis or dredd), and that an OpenAPI description is checked for breaking changes against
the main branch's (`schema-compatibility`: `oasdiff breaking`, its action, openapi-diff; the AsyncAPI CLI's `diff`
reports breaking changes without failing on them, so AsyncAPI is not asked)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from pathlib import PurePosixPath

from project_validator import yaml_support
from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.expansion import Action
from project_validator.facts.schema import (
    compatibility_checked,
    compatibility_checker,
    example_checker,
    examples_checked,
    validated,
    validator,
)
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import (
    Condition,
    Definition,
    Tool,
    all_of,
    combined,
    defined_by,
    starts,
    when,
    with_option,
)

OPENAPI, ASYNCAPI = "OpenAPI", "AsyncAPI"
OPENAPI_ONLY, ASYNCAPI_ONLY = frozenset({OPENAPI}), frozenset({ASYNCAPI})
API_FORMATS = OPENAPI_ONLY | ASYNCAPI_ONLY

# The top-level key, in YAML (`openapi: 3.1.0`, at the first column) or JSON (`"openapi": "3.1.0"`, indented once).
_DESCRIBES = {
    OPENAPI: re.compile(r"^(?:openapi|swagger)\s*:|^\s{0,4}\"(?:openapi|swagger)\"\s*:", re.MULTILINE),
    ASYNCAPI: re.compile(r"^asyncapi\s*:|^\s{0,4}\"asyncapi\"\s*:", re.MULTILINE),
}
_DESCRIPTION_SUFFIXES = (".yaml", ".yml", ".json")


def _described(project: Project) -> Iterator[tuple[str, str]]:
    """(path, format) of each of the project's YAML and JSON files that is an API description, by its top-level
    key."""
    for path in project.files():
        if PurePosixPath(path).suffix in _DESCRIPTION_SUFFIXES:
            head = project.read_head(path)
            yield from ((path, name) for name, key in _DESCRIBES.items() if key.search(head))


def api_descriptions(project: Project) -> frozenset[str]:
    """The API description formats among the project's YAML and JSON files, told by their top-level key."""
    return frozenset(name for _, name in _described(project))


def _descriptions_in(name: str) -> Callable[[Project], Iterator[str]]:
    return lambda project: (path for path, found in _described(project) if found == name)


API_ECOSYSTEM = Ecosystem(
    label="OpenAPI/AsyncAPI",
    kind="format",
    languages=API_FORMATS,
    detect=api_descriptions,
    ci_programs=(
        ("spectral",),
        ("spectral-cli",),
        ("redocly",),
        ("vacuum",),
        ("swagger-cli",),
        ("asyncapi",),
        ("schemathesis",),
        ("dredd",),
        ("oasdiff",),
        ("openapi-diff",),
    ),
    ci_usage=re.compile(r"(?<![\w-])(?:spectral-action|oasdiff-action)\b"),
)


# --- Declaration ----------------------------------------------------------------------------------------------------

_SUPERSEDED = {"swagger": "Swagger 2.0 is superseded by OpenAPI 3.0"}


def _read_description(*keys: str) -> Callable[[str], Declaration | None]:
    """What a description declares: its specification version (the top-level `openapi`, `swagger` or `asyncapi`) and
    its own version (`info.version`). One that does not parse as a YAML or JSON object declares nothing that can be
    read."""

    def read(text: str) -> Declaration | None:
        try:
            document = yaml_support.load(text)
        except yaml_support.YamlError:
            return None
        if not isinstance(document, dict):
            return None
        key = next((key for key in keys if key in document), keys[0])
        info = document.get("info")
        version = info.get("version") if isinstance(info, dict) else None
        return declaring({key: document.get(key), "info.version": version}, outdated=_SUPERSEDED.get(key))

    return read


OPENAPI_DECLARES = Declares(
    format=OPENAPI,
    what="version (openapi) and info.version",
    find=_descriptions_in(OPENAPI),
    read=_read_description("openapi", "swagger"),
)
ASYNCAPI_DECLARES = Declares(
    format=ASYNCAPI,
    what="version (asyncapi) and info.version",
    find=_descriptions_in(ASYNCAPI),
    read=_read_description("asyncapi"),
)


# --- Linting --------------------------------------------------------------------------------------------------------


def _linter(
    name: str,
    languages: frozenset[str],
    how: str,
    runs: Condition,
    rules: Definition | None = None,
    *,
    examples: bool = False,
) -> Tool:
    """A linter of API descriptions, which validates them against the specification and lints them at once; one
    whose rules validate the description's `examples` against their schemas checks those too."""
    tools = [
        validator(name=name, languages=languages, how=how, validates=when(runs, validated)),
        analyzer(name=name, languages=languages, how=how, analyses=when(runs, analysed), rules=rules),
    ]
    if examples:
        tools.append(example_checker(name=name, languages=languages, how=how, checks=when(runs, examples_checked)))
    return combined(*tools)


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
    examples=True,
)
REDOCLY_SETTINGS = file_reader("redocly", ("redocly.yaml", ".redocly.yaml", "redocly.yml", ".redocly.yml"))
REDOCLY = _linter(
    "redocly",
    OPENAPI_ONLY,
    "redocly lint <description>",
    starts(("redocly", "lint"), ("openapi", "lint")),
    defined_by(files=(REDOCLY_SETTINGS.name,)),
    examples=True,
)
VACUUM = _linter("vacuum", OPENAPI_ONLY, "vacuum lint <description>", starts(("vacuum", "lint")), examples=True)
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

# Contract tests run the described API against its description: every example, and more, is checked for real.
SCHEMATHESIS = example_checker(
    name="schemathesis",
    languages=OPENAPI_ONLY,
    how="schemathesis run <description> --url <base url> (or st run)",
    checks=when(starts(("schemathesis", "run"), ("st", "run")), examples_checked),
)
DREDD = example_checker(
    name="dredd",
    languages=OPENAPI_ONLY,
    how="dredd <description> <base url>",
    checks=when(starts(("dredd",)), examples_checked),
)

# --- Compatibility --------------------------------------------------------------------------------------------------

# `oasdiff breaking` fails on breaking changes (`--fail-on ERR` by default in CI use); `diff` and `changelog` only
# report. openapi-diff fails only when told to.
OASDIFF = compatibility_checker(
    name="oasdiff",
    languages=OPENAPI_ONLY,
    how="oasdiff breaking <main branch's description> <description> (or oasdiff/oasdiff-action/breaking)",
    checks=when(starts(("oasdiff", "breaking")), compatibility_checked),
)
OPENAPI_DIFF = compatibility_checker(
    name="openapi-diff",
    languages=OPENAPI_ONLY,
    how="openapi-diff <main branch's description> <description> --fail-on-incompatible",
    checks=when(
        all_of(starts(("openapi-diff",)), with_option("--fail-on-incompatible", "--fail-on-changed")),
        compatibility_checked,
    ),
)


def _oasdiff_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`oasdiff/oasdiff-action/breaking` runs `oasdiff breaking` on its `base` and `revision` inputs."""
    return (("oasdiff", "breaking", inputs.get("base", ""), inputs.get("revision", "")),)


OASDIFF_ACTION = Action(name="oasdiff/oasdiff-action/breaking", runs=_oasdiff_action)

SPECTRAL_ACTION = Action(
    name="stoplightio/spectral-action",
    runs=lambda inputs: (("spectral", "lint", *inputs.get("file_glob", "*.yaml").split()),),
)
