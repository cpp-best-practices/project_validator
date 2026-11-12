"""The XML schemas profile: schemas validated with xmllint, jing or SchXslt; stylesheets tested with XSpec; both
formatted with prettier."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.schema_validation import schema_validation
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.xml_schemas import XML_SCHEMAS_ECOSYSTEM
from tests.layouts.xml_schemas import XSD, XSL
from tests.support import github_job, make_context, run_in_layout, temp_project, uses

VALIDATED = "CI validates the documents against their schemas with {}"
XSPEC = {
    "tests/total.xspec": (
        '<?xml version="1.0"?>\n<x:description xmlns:x="http://www.jenitennison.com/xslt/xspec" '
        'stylesheet="../xslt/total.xsl">\n  <x:scenario label="sums"><x:context><catalog/></x:context>'
        '<x:expect label="zero">0</x:expect></x:scenario>\n</x:description>\n'
    )
}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_schemas_and_stylesheets_are_told_by_their_suffixes(self) -> None:
        cases = (
            ({"schema/catalog.xsd": XSD}, {"XML Schema", "XML"}),
            ({"schema/catalog.rng": "<grammar xmlns='http://relaxng.org/ns/structure/1.0'/>\n"}, {"XML Schema", "XML"}),
            ({"schema/catalog.rnc": "start = element catalog { empty }\n"}, {"XML Schema"}),
            ({"rules/catalog.sch": "<schema xmlns='http://purl.oclc.org/dsdl/schematron'/>\n"}, {"XML Schema", "XML"}),
            ({"xslt/total.xsl": XSL}, {"XSLT", "XML"}),
            ({"xslt/total.xslt": XSL, **XSPEC}, {"XSLT", "XML"}),
        )
        for files, formats in cases:
            with self.subTest(files=files), temp_project(files) as root:
                structure = make_context(root).structure
                self.assertEqual((structure.languages, structure.formats), (frozenset(), frozenset(formats)))
                self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"data/catalog.xml": "<catalog/>\n"}) as root:
            self.assertEqual(make_context(root).structure.formats, frozenset({"XML"}))
        self.assertEqual((XML_SCHEMAS_ECOSYSTEM.kind, XML_SCHEMAS_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in ("xmllint --noout --schema s.xsd d.xml", "jing s.rng d.xml", "xspec.sh -t tests/total.xspec"):
            with self.subTest(text=text):
                self.assertTrue(uses(XML_SCHEMAS_ECOSYSTEM, text))
        self.assertFalse(uses(XML_SCHEMAS_ECOSYSTEM, "npm test"))


class XmlSchemaTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, "XML Schema", selected, files)

    def test_the_documents_are_validated_against_the_schemas(self) -> None:
        for line, tool in (
            ("xmllint --noout --schema schema/catalog.xsd data/catalog.xml", "xmllint"),
            ("xmllint --relaxng schema/catalog.rng data/*.xml", "xmllint"),
            ("xmllint --noout --schematron rules.sch data/catalog.xml", "xmllint"),
            ("jing schema/catalog.rng data/catalog.xml", "jing"),
            ("schxslt -s rules.sch -d data/catalog.xml", "SchXslt"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(schema_validation, _ci(line)), Result.passed(VALIDATED.format(tool)))
        # xmllint without a schema only parses.
        self.assertEqual(self._run(schema_validation, _ci("xmllint --noout data/catalog.xml")).status, Status.FAIL)
        self.assertEqual(self._run(data_wellformed, {}).status, Status.PASS)

    def test_prettier_formats_the_schemas(self) -> None:
        checked = _ci("npx --yes prettier --plugin=@prettier/plugin-xml --check schema")
        self.assertEqual(self._run(code_formatting, checked), Result.passed("CI enforces the prettier style"))
        self.assertEqual(self._run(code_formatting, _ci("prettier --write schema")).status, Status.FAIL)


class XsltTests(unittest.TestCase):
    def test_xspec_runs_the_stylesheets_suites(self) -> None:
        for line in ("xspec.sh -t tests/total.xspec", "xspec -t tests/total.xspec", "xspec.bat -t tests/total.xspec"):
            with self.subTest(line=line):
                result = run_in_layout(self, "XSLT stylesheet", tests_run, {**XSPEC, **_ci(line)})
                self.assertEqual(result, Result.passed("tests found in 1 file(s)"))
        self.assertEqual(
            run_in_layout(self, "XSLT stylesheet", tests_run, {**XSPEC, **_ci("prettier --check .")}).status,
            Status.WARN,
        )
        self.assertEqual(
            run_in_layout(self, "XSLT stylesheet", tests_run, _ci("xspec.sh -t tests/total.xspec")).status, Status.FAIL
        )
        # A schema project has no stylesheet to test.
        self.assertEqual(
            run_in_layout(self, "XML Schema", tests_run, _ci("xspec.sh -t tests/total.xspec")).status, Status.SKIP
        )
