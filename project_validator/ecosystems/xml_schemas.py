"""XML schemas and stylesheets: two formats recognised by intent. XML Schema holds the schemas (`.xsd`, RELAX NG's
`.rng` and `.rnc`, Schematron's `.sch`), whose documents CI validates (`schema-validation`: `xmllint --schema`,
`--relaxng` or `--schematron`, jing, SchXslt). XSLT holds the stylesheets (`.xsl`, `.xslt`), whose XSpec suites CI
runs (`tests-run`). Both are formatted with prettier and its XML plugin (`code-formatting`). The files are XML, the
Data format's, whose parser never fetches an external DTD or entity; `.rnc`, RELAX NG's compact syntax, is accounted
for without being XML. An XSD declares its `targetNamespace` (`schema-declared`); RELAX NG and Schematron schemas
name no namespace of their own and are not asked; a validator run on an `examples` directory checks the schemas'
examples (`schema-examples`). A document naming its schema (`xsi:schemaLocation`) is the other schema practice of #86,
not yet built."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, resolved
from project_validator.facts.arguments import has_option, program
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.schema import example_checker, examples_checked, names_examples, validated, validator
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import all_of, combined, starts, when
from project_validator.tools.prettier import prettier_tool

XML_SCHEMA, XSLT = "XML Schema", "XSLT"
XML_SCHEMA_ONLY, XSLT_ONLY = frozenset({XML_SCHEMA}), frozenset({XSLT})
XML_FORMATS = XML_SCHEMA_ONLY | XSLT_ONLY
XML = frozenset({"XML"})

_SUFFIXES = {XML_SCHEMA: frozenset({".xsd", ".rng", ".rnc", ".sch"}), XSLT: frozenset({".xsl", ".xslt"})}


def xml_schemas(project: Project) -> frozenset[str]:
    """The formats among the project's files: schemas by their suffixes, stylesheets by theirs."""
    suffixes = {PurePosixPath(path).suffix.lower() for path in project.files()}
    return frozenset(name for name, own in _SUFFIXES.items() if suffixes & own)


XML_SCHEMAS_ECOSYSTEM = Ecosystem(
    label="XML schemas",
    kind="format",
    languages=XML_FORMATS,
    # RELAX NG's compact syntax is not XML; it belongs to the schemas without being a format of its own.
    ambiguous_suffixes={".rnc": None},
    detect=xml_schemas,
    ci_programs=(("xmllint",), ("jing",), ("schxslt",), ("xspec",), ("xspec.sh",), ("xspec.bat",)),
)


# --- Declaration ----------------------------------------------------------------------------------------------------

_SCHEMA_ELEMENT = re.compile(r"<(?:[\w.-]+:)?schema\b([^>]*)>")
_TARGET_NAMESPACE = re.compile(r"\btargetNamespace\s*=\s*[\"']([^\"']*)[\"']")


def xsd_files(project: Project) -> Iterator[str]:
    return (path for path in project.files() if PurePosixPath(path).suffix.lower() == ".xsd")


def _read_xsd(text: str) -> Declaration | None:
    """What an XSD declares: the `targetNamespace` of its `schema` element; a file with no such element declares
    nothing that can be read."""
    element = _SCHEMA_ELEMENT.search(text)
    if element is None:
        return None
    namespace = _TARGET_NAMESPACE.search(element[1])
    return declaring({"targetNamespace": namespace[1] if namespace else None})


XSD_DECLARES = Declares(format=XML_SCHEMA, what="targetNamespace", find=xsd_files, read=_read_xsd)


# --- Validation -----------------------------------------------------------------------------------------------------

_XMLLINT_SCHEMAS = ("--schema", "--relaxng", "--schematron", "--dtdvalid", "--valid")


def _xmllint_with_schema(command: Command) -> bool:
    """xmllint validates when given a schema (`--schema x.xsd`, `--relaxng x.rng`, `--schematron x.sch`); alone it
    only parses."""
    argv = resolved(command)
    return program(argv) == "xmllint" and has_option(argv, *_XMLLINT_SCHEMAS)


# A validator run on an `examples` directory checks the schema's examples.
XMLLINT = combined(
    validator(
        name="xmllint",
        languages=XML_SCHEMA_ONLY,
        how="xmllint --noout --schema <schema> <documents> (or --relaxng, --schematron)",
        validates=when(_xmllint_with_schema, validated),
    ),
    example_checker(
        name="xmllint",
        languages=XML_SCHEMA_ONLY,
        how="xmllint --noout --schema <schema> examples/valid/*.xml",
        checks=when(all_of(_xmllint_with_schema, names_examples), examples_checked),
    ),
)
JING = combined(
    validator(
        name="jing",
        languages=XML_SCHEMA_ONLY,
        how="jing <schema> <documents> (RELAX NG, or an XSD with -c)",
        validates=when(starts(("jing",)), validated),
    ),
    example_checker(
        name="jing",
        languages=XML_SCHEMA_ONLY,
        how="jing <schema> examples/valid/*.xml",
        checks=when(all_of(starts(("jing",)), names_examples), examples_checked),
    ),
)
SCHXSLT = validator(
    name="SchXslt",
    languages=XML_SCHEMA_ONLY,
    how="schxslt -s <schema.sch> -d <document>",
    validates=when(starts(("schxslt",), ("schxslt-cli",)), validated),
)


# --- XSpec: the stylesheets' tests ----------------------------------------------------------------------------------

XSPEC_SUITES = TestFiles(
    name="XSpec suites (*.xspec)",
    languages=XSLT_ONLY,
    path=re.compile(r"\.xspec$"),
    contains=re.compile(r"<x:description\b"),
    written_in=XML,
)
XSPEC = test_runner(
    name="XSpec",
    languages=XSLT_ONLY,
    how="xspec.sh -t tests/*.xspec (or the XSpec Maven or Ant targets)",
    runs=when(starts(("xspec",), ("xspec.sh",), ("xspec.bat",)), tested),
    tests=tests_of(XSPEC_SUITES.name),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# prettier formats XML with @prettier/plugin-xml.
PRETTIER = prettier_tool(XML_FORMATS)
