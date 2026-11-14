"""GraphQL: schemas in the schema definition language (`.graphqls`; or `.graphql` and `.gql` files holding type
definitions, or named `schema.graphql`) and the operations written against them, a format recognised by intent: a
`.graphql` file of operations alone (a client's queries) counts once a schema, or a GraphQL Config file
(`.graphqlrc`, `graphql.config.*`), shows the project is a GraphQL one. What is asked is that CI builds the schema and
validates the operations against it (`schema-validation`: `graphql-inspector validate`, or GraphQL Code Generator,
which fails on an invalid document), lints the schema (`static-analysis`: graphql-schema-linter, or eslint with
`@graphql-eslint/eslint-plugin`), formats it (`code-formatting`: prettier) and checks it for breaking changes against
the main branch or a registry (`schema-compatibility`: `graphql-inspector diff`, its action, or Apollo's `rover graph
check`). A GraphQL schema names no dialect or identifier, so `schema-declared` does not ask; nothing checks examples
of a schema, so `schema-examples` does not either."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.javascript import ESLINT_CONFIG_FILES, PACKAGE_JSON
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, Setting
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.schema import compatibility_checked, compatibility_checker, validated, validator
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
from project_validator.facts.tools import Run, combined, defined_by, starts, when
from project_validator.tools.prettier import prettier_tool

GRAPHQL = "GraphQL"
GRAPHQL_ONLY = frozenset({GRAPHQL})

_SUFFIXES = (".graphql", ".gql", ".graphqls")
_SCHEMA_NAMES = frozenset({"schema.graphql", "schema.gql"})
_CONFIG = re.compile(r"^(?:\.graphqlrc(?:\.\w+)?|graphql\.config\.\w+)$")
# A type system definition at the start of a line: what a schema holds and an operations document does not (a field
# named `type` or `schema` is followed by a colon, a brace, an argument list or a line end, never by a name).
_DEFINITION = re.compile(
    r"^\s*(?:extend\s+)?(?:(?:scalar|type|interface|union|enum|input)\s+[A-Za-z_]\w*|schema\s*[{@]|directive\s*@)",
    re.MULTILINE,
)


def graphql_project(project: Project) -> frozenset[str]:
    """Whether the project holds a GraphQL schema: a `.graphqls` file, a `schema.graphql`, a `.graphql` or `.gql` file
    with type definitions, or a GraphQL Config file naming one."""
    for path in project.files():
        name = PurePosixPath(path).name
        if name in _SCHEMA_NAMES or name.endswith(".graphqls") or _CONFIG.match(name):
            return GRAPHQL_ONLY
        if name.endswith(_SUFFIXES) and _DEFINITION.search(project.read_head(path)):
            return GRAPHQL_ONLY
    return frozenset()


GRAPHQL_ECOSYSTEM = Ecosystem(
    label="GraphQL",
    kind="format",
    languages=GRAPHQL_ONLY,
    source_suffixes={".graphqls": GRAPHQL},
    # Operations documents are the format's too, once a schema shows the project is a GraphQL one.
    ambiguous_suffixes={".graphql": GRAPHQL, ".gql": GRAPHQL},
    detect=graphql_project,
    ci_programs=(
        ("graphql-inspector",),
        ("@graphql-inspector/cli",),
        ("graphql-codegen",),
        ("@graphql-codegen/cli",),
        ("gql-gen",),
        ("graphql-schema-linter",),
        ("rover",),
    ),
    ci_usage=re.compile(r"(?<![\w-])(?:graphql-hive|kamilkisiela)/graphql-inspector\b"),
)

GRAPHQL_SCHEMA_LINTER_SETTINGS = file_reader("graphql-schema-linter", (".graphql-schema-linterrc",))


# --- Validation and compatibility -----------------------------------------------------------------------------------

_INSPECTOR = (("graphql-inspector",), ("@graphql-inspector/cli",))


def _inspector(*subcommands: str) -> tuple[tuple[str, ...], ...]:
    return tuple((*program, subcommand) for program in _INSPECTOR for subcommand in subcommands)


# `validate` checks the operations against the schema; `introspect` and `diff` build the schema, which an invalid one
# fails; `diff` also fails on a breaking change against the schema it is given (the main branch's, a registry's).
GRAPHQL_INSPECTOR = combined(
    validator(
        name="graphql-inspector",
        languages=GRAPHQL_ONLY,
        how="graphql-inspector validate 'operations/**/*.graphql' schema.graphql",
        validates=when(starts(*_inspector("validate", "introspect", "diff")), validated),
    ),
    compatibility_checker(
        name="graphql-inspector",
        languages=GRAPHQL_ONLY,
        how="graphql-inspector diff <main branch's schema> schema.graphql (or graphql-hive/graphql-inspector)",
        checks=when(starts(*_inspector("diff")), compatibility_checked),
    ),
)
# GraphQL Code Generator builds the schema and the documents' types; an invalid document fails it.
GRAPHQL_CODEGEN = validator(
    name="graphql-codegen",
    languages=GRAPHQL_ONLY,
    how="graphql-codegen --config codegen.ts",
    validates=when(starts(("graphql-codegen",), ("@graphql-codegen/cli",), ("gql-gen",)), validated),
)
# rover checks a schema against the graph Apollo Studio holds and the operations it has seen.
ROVER = compatibility_checker(
    name="rover",
    languages=GRAPHQL_ONLY,
    how="rover graph check <graph>@<variant> --schema schema.graphql (or rover subgraph check)",
    checks=when(starts(("rover", "graph", "check"), ("rover", "subgraph", "check")), compatibility_checked),
)


def _graphql_inspector_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`graphql-hive/graphql-inspector` (once `kamilkisiela/graphql-inspector`) diffs the pull request's schema against
    the one its `schema` input names (`main:schema.graphql`) and fails on a breaking change unless `fail-on-breaking`
    is false, when it only annotates."""
    if inputs.get("fail-on-breaking", "true").strip().lower() == "false":
        return ()
    return (("graphql-inspector", "diff", *inputs.get("schema", "").split()),)


GRAPHQL_INSPECTOR_ACTION = Action(name="graphql-hive/graphql-inspector", runs=_graphql_inspector_action)
GRAPHQL_INSPECTOR_ACTION_OLD = Action(name="kamilkisiela/graphql-inspector", runs=_graphql_inspector_action)


# --- Analysis -------------------------------------------------------------------------------------------------------

# graphql-schema-linter has every rule on by default; `.graphql-schema-linterrc` (or package.json's
# `graphql-schema-linter` key) chooses.
GRAPHQL_SCHEMA_LINTER = analyzer(
    name="graphql-schema-linter",
    languages=GRAPHQL_ONLY,
    how="graphql-schema-linter 'schema/**/*.graphql'",
    analyses=when(starts(("graphql-schema-linter",)), analysed),
    rules=defined_by(files=(GRAPHQL_SCHEMA_LINTER_SETTINGS.name,)),
)

# eslint lints GraphQL with @graphql-eslint/eslint-plugin, named where eslint reads its configuration or in
# package.json.
_GRAPHQL_PLUGIN = re.compile(r"@graphql-eslint/(?:eslint-plugin|[\w-]+)\b|\bplugin:@graphql-eslint/")
GRAPHQL_ESLINT_RULES = SettingsReader(
    name="graphql-eslint",
    files=(*ESLINT_CONFIG_FILES, PACKAGE_JSON),
    read=lambda path, text: matched_settings("eslint", path, text, {"graphql plugin": (_GRAPHQL_PLUGIN, True)}),
)


def _graphql_eslint(command: Command, facts: Facts) -> Run | None:
    if not starts(("eslint",))(command):
        return None
    read = facts.where(Setting, tool="eslint", key="graphql plugin")
    return analysed(read=read) if read else None


GRAPHQL_ESLINT = analyzer(
    name="graphql-eslint",
    languages=GRAPHQL_ONLY,
    how="eslint with @graphql-eslint/eslint-plugin",
    analyses=_graphql_eslint,
    reads=(GRAPHQL_ESLINT_RULES.name,),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# prettier formats GraphQL; its configuration is the JavaScript profile's to read.
PRETTIER = prettier_tool(GRAPHQL_ONLY)
