"""XML schemas and stylesheets: two formats recognised by intent. XML Schema holds the schemas (`.xsd`, RELAX NG's
`.rng` and `.rnc`, Schematron's `.sch`), whose documents CI validates (`schema-validation`: `xmllint --schema`,
`--relaxng` or `--schematron`, jing, SchXslt). XSLT holds the stylesheets (`.xsl`, `.xslt`), whose XSpec suites CI
runs (`tests-run`). Both are formatted with prettier and its XML plugin (`code-formatting`). The files are XML, the
Data format's, whose parser never fetches an external DTD or entity; `.rnc`, RELAX NG's compact syntax, is accounted
for without being XML. An XSD declares its `targetNamespace`, and each document of one of the project's XSDs (its
root element in the schema's namespace, or a global element of a schema with none) names the schema's location
(`xsi:schemaLocation`, `xsi:noNamespaceSchemaLocation`, or an `xml-model` processing instruction), so that an editor
or a validator finds it (`schema-declared`); RELAX NG and Schematron schemas name no namespace of their own and are
not asked, and `elementFormDefault` is a choice with a defined default, not a declaration. A validator run on an
`examples` directory checks the schemas' examples (`schema-examples`)."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from xml.etree import ElementTree

from project_validator.core import Project
from project_validator.ecosystems.jvm import Wiring, wired_run
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option, program
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.schema import example_checker, examples_checked, names_examples, validated, validator
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, all_of, combined, starts, when
from project_validator.tools.prettier import prettier_tool

XML_SCHEMA, XSLT = "XML Schema", "XSLT"
XML_SCHEMA_ONLY, XSLT_ONLY = frozenset({XML_SCHEMA}), frozenset({XSLT})
XML_FORMATS = XML_SCHEMA_ONLY | XSLT_ONLY
XML = frozenset({"XML"})

# XSD, RELAX NG (and its compact syntax), Schematron and NVDL.
_SUFFIXES = {XML_SCHEMA: frozenset({".xsd", ".rng", ".rnc", ".sch", ".nvdl"}), XSLT: frozenset({".xsl", ".xslt"})}


def xml_schema_files(project: Project) -> Iterator[tuple[str, str]]:
    """(path, format) of each of the project's schemas, by its suffix, and stylesheets, by theirs."""
    for path in project.files():
        suffix = PurePosixPath(path).suffix.lower()
        yield from ((path, name) for name, own in _SUFFIXES.items() if suffix in own)


XML_SCHEMAS_ECOSYSTEM = Ecosystem(
    label="XML schemas",
    links={"XML Schema": "https://www.w3.org/XML/Schema", "XSLT": "https://www.w3.org/TR/xslt-30/"},
    kind="format",
    languages=XML_FORMATS,
    # RELAX NG's compact syntax and DTDs are not XML; they belong to the schemas without being formats of their own.
    # A DTD (with its entity files and the modules of declarations it includes, docbook's `dbpoolx.mod`) is a schema
    # project's; alone it describes a program's own configuration (glib's gschema.dtd, dbus-broker's config.dtd),
    # which makes no schema project. `.mod` is also a compiled Fortran module, or Modula-2, so it is never told alone.
    ambiguous_suffixes={".rnc": None, ".dtd": None, ".ent": None, ".mod": None},
    locate=xml_schema_files,
    ci_programs=(("xmllint",), ("jing",), ("onvdl",), ("schxslt",), ("xspec",), ("xspec.sh",), ("xspec.bat",)),
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

_XS, _XSI = "{http://www.w3.org/2001/XMLSchema}", "{http://www.w3.org/2001/XMLSchema-instance}"
_XML_MODEL = re.compile(r"<\?xml-model\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']")


def _root(text: str) -> ElementTree.Element | None:
    """The root element of an XML document, with its attributes, read no further; None when it does not parse (the
    parser fetches nothing: no external entity is read)."""
    try:
        events = ElementTree.iterparse(io.StringIO(text), events=("start",))  # noqa: S314
        root: ElementTree.Element | None = next((element for _, element in events), None)
    except ElementTree.ParseError:
        return None
    return root


def _schema_targets(project: Project) -> tuple[frozenset[str], frozenset[str]]:
    """What the project's XSDs describe: the namespaces of those with a `targetNamespace`, and the global elements of
    those without one, which a document of theirs has as its root."""
    namespaces: set[str] = set()
    elements: set[str] = set()
    for path in xsd_files(project):
        try:
            schema = ElementTree.fromstring(project.read_text(path))  # noqa: S314 - the project's own files
        except ElementTree.ParseError:
            continue
        if schema.tag != f"{_XS}schema":
            continue
        if namespace := schema.get("targetNamespace"):
            namespaces.add(namespace)
        else:
            elements.update(name for element in schema.iterfind(f"{_XS}element") if (name := element.get("name")))
    return frozenset(namespaces), frozenset(elements)


def schema_documents(project: Project) -> Iterator[str]:
    """The XML documents of the project's XSDs: each `.xml` file whose root element is in a schema's namespace, or is
    a global element of a schema with none. Other XML (a build file, a stylesheet) is of other schemas."""
    namespaces, elements = _schema_targets(project)
    if not namespaces and not elements:
        return
    for path in project.files():
        if PurePosixPath(path).suffix.lower() != ".xml" or (root := _root(project.read_text(path))) is None:
            continue
        namespace, _, name = root.tag.rpartition("}")
        if (namespace and namespace[1:] in namespaces) or (not namespace and name in elements):
            yield path


def _read_document(text: str) -> Declaration | None:
    """Where a document says its schema is: `xsi:schemaLocation` (or `xsi:noNamespaceSchemaLocation`) on its root
    element, or an `xml-model` processing instruction before it. One that does not parse in full declares nothing that
    can be read (`data-wellformed` says so)."""
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 - the project's own files, parsed without fetching anything
    except ElementTree.ParseError:
        return None
    model = _XML_MODEL.search(text)
    location = root.get(f"{_XSI}schemaLocation") or root.get(f"{_XSI}noNamespaceSchemaLocation")
    return declaring({"schema location": location or (model[1] if model else None)})


XML_DOCUMENT_DECLARES = Declares(format=XML_SCHEMA, what="schema location", find=schema_documents, read=_read_document)


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
# onvdl, jing's NVDL validator: an NVDL script dispatches each part of a document to the schema for its namespace.
ONVDL = validator(
    name="onvdl",
    languages=XML_SCHEMA_ONLY,
    how="onvdl <script.nvdl> <documents>",
    validates=when(starts(("onvdl",)), validated),
)
# Norm Walsh's RELAX NG validation plugin for Gradle (docbook's build): its validation tasks run in the build.
_RELAXNG_PLUGIN = Wiring(
    report=re.compile(r"\w*[Rr]elax[Nn][Gg]\w*"),
    maven_plugin="relaxng-maven-plugin",
    bound_goal=None,
    gradle_plugin="com.nwalsh.gradle.relaxng.validate",
)


def _relaxng_plugin(command: Command, facts: Facts) -> Run | None:
    read = wired_run(_RELAXNG_PLUGIN, command, facts)
    return None if read is None else validated(read=read)


RELAXNG_GRADLE = validator(
    name="the RELAX NG validation Gradle plugin",
    languages=XML_SCHEMA_ONLY,
    how="the com.nwalsh.gradle.relaxng.validate Gradle plugin, in a build CI runs",
    validates=_relaxng_plugin,
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
