# Data

The formats a project's data and configuration are written in: JSON (`.json`, `.jsonc`), TOML (`.toml`), YAML
(`.yaml`, `.yml`) and XML (`.xml`, `.xsd`, `.xsl`, `.xslt`). A format, not a language: it has no toolchain, tests,
coverage or dependencies, so none of those checks applies, and its files make no language the project's (a C++ project
with a workflow file is not a YAML project; `--map` lists `formats` beside `languages`). What is asked of a format is
hygiene.

Data files are recognised in the project and in its configuration directories (`.github`, `.gitlab`, `.circleci`,
`.buildkite`, `.devcontainer`, `.vscode`), where a language's sources are not: a CI workflow is judged as the YAML it
is. Vendored files (`third_party/`, `vendor/`) are not read.

## `data-wellformed`

Every file parses, judged per format in each unit of the project whose files are in it. JSON that tools read with
comments (`*.jsonc`, `tsconfig*.json`, `jsconfig.json`, `devcontainer.json`, `.vscode/*.json`) may have comments and
trailing commas; YAML tags of any tool (GitLab's `!reference`) are accepted; XML external entities are never read; JSON
nested deeper than Python recurses is read without recursion. Files over 5 MiB are not parsed, and said so. A test
suite's data files (`tests/`, `spec/`, `fixtures/`, ...) are read but only reported, not judged: a parser's test data
is malformed on purpose.
