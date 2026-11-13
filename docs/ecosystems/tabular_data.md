# Tabular data

A format, Data Package, recognised by intent: a Frictionless Data Package descriptor (`datapackage.json`,
`datapackage.yaml`), a Table Schema (`tableschema.json`), or a JSON or YAML file whose `$schema` or `profile` names
a Data Package profile (datapackage.org, frictionlessdata.io, `tabular-data-package`) makes the project a tabular
data one. A CSV alone is a table of no declared schema and makes nothing (`.csv` and `.tsv` are data, never
sources). The descriptors stay JSON or YAML, the Data format's, so `data-wellformed` already covers one that does
not parse.

A CI job works with the ecosystem when it runs frictionless, goodtables or csvlint, or the
`frictionlessdata/frictionless-ci` action (once `frictionlessdata/repository`).

## `schema-validation`

CI validates the tables against their schemas: `frictionless validate datapackage.json` (a package, a resource, or a
table with `--schema`; `describe` and `extract` only read them), or the `frictionlessdata/frictionless-ci` action,
which validates the inquiry, packages, resources or tables its inputs name, and the repository's data packages when
told nothing; `goodtables validate`, its predecessor; `csvlint --schema=<table schema> <table>` (without a schema,
csvlint checks that the CSV is well formed, against nothing).

## Not judged

A `dvc.yaml` alone shows data versioning, not a schema to validate against, and `large-files` already accepts a file
DVC tracks, so it recognises nothing here. The other schema practices of #85 (`schema-declared`, `schema-examples`,
`schema-compatibility`) are not yet built. The language practices have no tool for a table and are skipped.
