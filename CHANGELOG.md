# Changelog

Each release's changes. The validator is at 0.x: what a release promises is in the README's
[Stability](README.md#stability) section. A JSON format or the score whose version changes says so here.

## 0.1.0

The first release.

- **What it does:** it validates a project's build, CI and tooling against best practices. It recognises the
  project's languages, formats, build systems and units, reads its CI (GitHub Actions, GitLab CI, Azure Pipelines,
  CircleCI, Cirrus CI and more) and what each job runs, and judges each language by its own ecosystem's tools. Each
  check reports PASS, WARN, FAIL, ERROR or SKIP; unknown answers are errors unless `--allow-unknown` is given.
- **What it prints:** a console report, plain text, Markdown, HTML and JSON, a terminal UI (`--tui`), and the tooling
  score (`--score`, score version 1).
- **The JSON formats,** each at version 1: `results`, `map`, `facts`, `answers`, `checks` and `support-matrix`.
- **The command** is `project_validator`; `project-validator`, its old name, still runs for this release and says it
  is deprecated.
