# XML schemas

Two formats recognised by intent, from the files' suffixes. **XML Schema** is the schemas: XSD (`.xsd`), RELAX NG
(`.rng`, and `.rnc`, the compact syntax, which is not XML) and Schematron (`.sch`). **XSLT** is the stylesheets
(`.xsl`, `.xslt`). The files are XML, the Data format's, whose parser never fetches an external DTD or entity, so
`data-wellformed` already covers one that does not parse; XSpec suites (`.xspec`) are XML too.

A CI job works with the ecosystem when it runs xmllint, jing, SchXslt or XSpec.

## `schema-validation`

CI validates the documents against the schemas: `xmllint --noout --schema <schema> <documents>` (or `--relaxng`,
`--schematron`; xmllint alone only parses), `jing <schema> <documents>`, or SchXslt for Schematron.

## `tests-run`

The stylesheets' XSpec suites (`*.xspec` with an `x:description`), run by `xspec.sh -t` (or the XSpec Maven or Ant
targets, which CI runs as `mvn test`).

## `code-formatting`

prettier with `@prettier/plugin-xml` (`prettier --plugin=@prettier/plugin-xml --check`), with its configuration where
the JavaScript profile reads it.

## `schema-declared`

Every XSD declares its `targetNamespace`. RELAX NG and Schematron schemas name no namespace of their own and are not
asked.

## `schema-examples`

xmllint (with a schema) or jing run on an `examples` (or `samples`, `valid`, `invalid`) directory checks the schemas'
examples. Warns when CI checks none.

## Not judged

The other schema practices of #86 are not yet built: a schema's `elementFormDefault`, a document naming its schema (`xsi:schemaLocation`, `<?xml-model?>`), and valid and invalid example documents. The
other checks have no tool for schemas or stylesheets and are skipped.
