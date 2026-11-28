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
  score (`--score`, score version 6). "About the project" shows what is learned without being judged: the versions
  each language declares (`requires-python`, `rust-version`, the `go` directive, `engines`, the C and C++ standard,
  and the pins of `.python-version`, `rust-toolchain.toml` and `.nvmrc`) beside the versions CI tests; each
  language's lines by role and how much is generated; each package manager's direct dependencies, manifests and
  lockfiles, and the vendored code; the license files beside what the manifests declare, the sources' SPDX headers,
  and the licenses of vendored code; the repository's age, its last year's commits, authors and signed commits, and
  its version tags, how often they come and whether the manifests' version is the latest tag's; every tool CI runs, by
  what it does and at the version it is pinned at; the events CI runs on, whether pull requests from forks run it,
  and its jobs, OSes and architectures; where releases are published,
  by trusted publishing or with provenance, and any SBOM or attestation; and the docs generator, the changelog's
  latest entry, CONTRIBUTING, CODEOWNERS and the issue and pull request templates. Online (unless `--offline`), it
  shows what the source-control host says beyond its settings: GitHub's metadata (archived, a fork, visibility, topics,
  homepage, the licence it detects), activity (open issues and pull requests, stale pull requests, the median time to
  close and to merge), open Dependabot and code scanning alerts where the token can read them, private vulnerability
  reporting, the latest release, and CI on the default branch's latest commit. `--ask-services` adds what outside
  services say: the OpenSSF Scorecard score, and the latest version PyPI, crates.io and npm publish beside the
  manifest's.
- **The policy tables** behind the score and the unknowns are TOML files in `project_validator/policy/`: strength
  weights, each tool's key and blanket diagnostics with their reasons, the score's levels and weights, and the
  actions known to run none of the project's code. Score version 6 counts ruff's linter and flake8 as one family for
  the extra credit, as the families table always meant; it had named ruff by a name no tool has.
- **The JSON formats,** each at version 1: `results`, `map`, `facts`, `answers`, `checks` and `support-matrix`.
- **The command** is `project_validator`; `project-validator`, its old name, still runs for this release and says it
  is deprecated.
