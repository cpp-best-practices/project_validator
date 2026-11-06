# Architecture

project_validator learns as much as it can about a project into a database of facts, answers questions about the
project from those facts, and judges the answers against a policy. Knowing how to read a build system, a tool or a CI
configuration is kept apart from deciding what a well-run project needs.

```
 project files ──► extractors ──► facts ──► questions ──► answers ──► policy ──► check results
                   (parse)        (database)  (query)     (machine-     (judge)
                                                          readable)
```

This document describes the target design and the migration to it. Sections marked **Today** describe the code as it
is; the rest is the design new work moves towards.

## Why

Today each language profile (`project_validator/ecosystems/<name>.py`) supplies a typed rule to each practice: the
regular expressions that recognise its tools, where to look for them, and what counts as passing. Detection and
requirements are mixed in one object, so:

- Adding a language touched about 25 shared files: the registry, test tables, the README's per-check rows, and the
  snapshot of every other fixture (the skip message listed every language). Two profiles developed side by side
  conflicted in all of them.
- Knowledge that is not about one language had to live in one: CMake belongs to the C/C++ profile, although it also
  builds Fortran, CUDA and Swift; gcov, llvm-cov, lizard and the sanitizers are copied or special-cased per profile;
  the CI layer parses Cargo, SwiftPM and Xcode build types itself.
- A profile that cannot meet a requirement (Go has no branch coverage, nothing measures F# function length) needs a
  special case, in the profile and in the tests.

## Layers

### Extractors

An extractor reads one kind of thing it understands and records facts. Extractors are the plugin surface: adding a
language, a build system, a tool or a CI provider means adding extractors, and nothing else changes.

| Kind | Reads | Examples |
|---|---|---|
| CI provider | CI configuration | GitHub Actions, GitLab CI, CircleCI: jobs, their OS, toolchains and environment, and the commands each step runs |
| Command expansion | what a command runs in turn | npm, Deno and Composer scripts, Rake tasks, Make recipes, CMake presets, Maven lifecycle phases, pre-commit hooks |
| Build system | build files | CMake, Meson, Bazel, Cargo, Gradle, Maven, MSBuild, SwiftPM, Xcode: the languages built, settings and their scope, build types, build trees and outputs, the test runner |
| Toolchain | compiler and interpreter settings | GCC, Clang, MSVC, gfortran, rustc, swiftc, CPython: warning, hardening, sanitizer and coverage instrumentation flags |
| Tool | a tool's invocation and configuration | gcovr, coverage.py, eslint, clang-tidy, lizard, osv-scanner, SwiftLint: what it measures or enforces, and for which files |
| Language | source files | which languages a project uses, by suffix and by content |
| Repository | the files themselves | committed artifacts, ignore rules, licences, security policy, large files |

Extractors run in stages, and each one declares the fact types it reads and writes: files and recognition, then build
systems and CI, then command expansion, then tool runs and settings, then the joins that decide what is in effect.

A component lives with the only language that uses it (Cargo, Composer, Bundler) until a second language needs it;
then a small refactor moves it into a shared module before the second language is added.

### Facts

A fact is a typed, immutable record. Every fact has:

- **a subject**: what was found, e.g. "gcovr runs with branch metrics", "`-Werror` is set", "job `linux-gcc13`
  exists".
- **a scope**: the languages, files or targets it covers, and the CI jobs (OS, toolchain, build configuration) it
  is in effect for. Scope is what lets one fact serve several languages: `add_compile_options(-Werror)` in CMake
  covers every language CMake compiles with a GCC-style compiler, Fortran included; `CMAKE_CXX_FLAGS` covers C++
  only.
- **provenance**: how it was found, for results and their details, e.g. `.github/workflows/ci.yml` job `test` →
  step 4 → `npm test` → `package.json` `scripts.test` → `vitest --coverage`.
- **confidence**: read from structured data, or matched by a heuristic.

A setting is in effect only when something CI runs reads it: an eslint configuration that enables
`max-lines-per-function` counts once eslint runs in a CI job, directly or through a script CI runs. Settings and
invocations are joined to decide what is in effect.

What could not be read is recorded too: a matrix computed by an expression, a reusable workflow in another
repository, a command no extractor understands. Absence of a fact is "no" only where nothing is unknown.

Commands are split into arguments, and extractors claim them by program and subcommand, rather than searching
command lines for a flag anywhere on the line.

Facts are Python dataclasses held in memory (`project_validator.facts.Facts`), queried by kind and field, by tool
setting and by the file a tool reads (see step 3½). They are exported as JSON by `--facts`.

### Questions

A question is a query over the facts that answers one thing about the project, per language: "what coverage is
reported for Python?", "are warnings errors for C++?", "which OS/toolchain/configuration combinations does CI build?"
Questions are the stable, machine-readable interface; checks and other consumers depend on them, never on
extractors.

An answer is one of:

- **yes**, with the facts that show it;
- **no**;
- **unknown**, with the reason (an unreadable matrix, a remote workflow);
- **impossible**: no known tool can provide it for the language. Go's tools measure statements, not branches; Swift's
  measure regions; nothing measures F# function length.

"Impossible" follows from what the known tools can do: tools declare their capability by facts that do not name our
languages (the file suffixes lizard parses, the lockfiles osv-scanner reads, the languages CodeQL analyses), so a new
language picks up every tool that already supports it. The same capabilities give the suggestions in results: "tools
known to report branch coverage for Rust: cargo-llvm-cov, grcov".

### Policy

A policy maps answers to statuses. For coverage: branch coverage is required (or the finest granularity possible for
the language, when branch coverage is impossible), and path or MC/DC coverage is a bonus. Checks become thin: a check
names its question and its policy and formats the result. `--strict` and `--warnings-as-errors` adjust the policy,
not the questions. The policy is built in to begin with; it is a separate layer so that it can be made configurable
later without touching extraction.

An **unknown** answer is a gap in the validator's tooling (configuration it cannot read, such as a CI provider it
only scans heuristically, or a matrix computed by an expression), not a finding about the project. So it is an
`ERROR`, which fails the run and names what was not read, unless the user passes `--allow-unknown`; then the answer
is judged by what could be read, as a no.

### Worked example: branch coverage in this repository

1. The GitHub Actions extractor records the job `coverage` and its command
   `["coverage", "run", "--branch", "-m", "unittest"]`.
2. The coverage.py extractor claims `coverage run` and records that coverage.py runs in that job, measuring lines
   and branches, for Python.
3. Without `--branch`, the same extractor reads the configuration coverage.py would read (`.coveragerc`, else the
   first of `setup.cfg`, `tox.ini` and `pyproject.toml` with coverage settings) for `branch = true`: the setting
   joins the run, and counts for nothing without one.
4. The coverage question answers for Python: lines yes, branches yes, paths impossible.
5. The coverage policy requires branches: PASS, with no path coverage suggestion, because none is possible.

## Invariants

Tests keep these from step 1 of the migration on:

- Adding a language, build system, tool or CI provider adds modules and fixtures and edits no shared list: built-in
  profiles and checks are discovered, and tests and documentation derive their expectations from the registry.
- A result names only the project's own languages; nothing in one fixture's results changes when an unrelated
  language is added.
- Checks do not name languages or tools.

## Migration

Each step is one pull request with every gate green. The snapshots (`tests/snapshots`) must be reproduced exactly,
except where a step deliberately changes results and says so.

1. **Discovery and derived expectations.** Built-in profiles are discovered like checks; each profile's fixtures,
   test layouts (`tests/layouts/<name>.py`) and documentation page (`docs/ecosystems/<name>.md`) are named after its
   module; tests derive their language lists from the registry; the README describes each check without per-language
   detail; the skip message stops listing every language.
2. **Facts and the CI command graph**, in three parts:
   1. The fact store (`project_validator/facts`) and the CI facts: each provider extracts its jobs (one per matrix
      combination), the commands each one runs (split by `project_validator/facts/shell.py`) with the step's
      condition, the actions it uses with their inputs, and what it could not read. `--facts` prints them.
   2. Command expansion (`project_validator/facts/expansion.py`): a `CommandExpander` says what a command runs in
      turn, and the commands found are expanded again, each with `via`, the chain that led to it. Expanders live
      with what they know and are found, not listed: package.json scripts and Deno tasks in the JavaScript profile,
      Composer scripts in the PHP profile, Make in `project_validator/build_systems`, pre-commit in
      `project_validator/tools`. Rake tasks, Maven lifecycle phases and CMake presets follow when their profiles
      move onto facts; presets and phases are settings rather than commands.
   3. The jobs the checks judge are built from the facts. A GitHub step or job whose condition is false for a
      combination yields no facts, and known expressions are evaluated (`project_validator/ci/github_expressions.py`).
      A job's evidence is what it runs: commands (with the variables its environment defines), image, environment,
      and action inputs whose values are known; step names and conditions are not evidence. Each build system reads
      the build types from its own commands (`BuildSystem.build_types`). Compilers and toolchain versions are still
      matched in that evidence, matrix values first (an action input that is switched off is not evidence);
      reading them structurally is the toolchain step (5).
3. **Coverage end to end.** Coverage extractors for every supported language, the coverage question and its policy;
   the `coverage` check moves to them and the `CoverageTools` rules are deleted.
   - A coverage tool records the languages it measures and each granularity it can measure (line, statement,
     region, branch, path) with how to ask for it, and claims the commands that run it by program and subcommand
     (since 3¾ an ordinary `Tool` with a `coverage` aspect). A claimed command is a run, joined with the
     configuration that command reads (`pytest` with its `addopts` and coverage.py's settings, `phpunit`
     with its XML, `dotnet test` with the MSBuild settings and `.runsettings`, `xcodebuild test` with the scheme,
     `cmake` configuring with the CMake files): a setting alone, which nothing CI runs reads, counts for nothing.
   - Launchers are command expanders that yield `Launched` commands: `bundle exec rake` runs `rake`, `npx c8` runs
     `c8`, `python -m coverage` runs `coverage`, `uv run pytest` runs `pytest`.
   - Components (command expanders and coverage tools) are found by `project_validator/components.py` in the
     shared build systems and tools and in the profiles (and their modules), never listed.
   - The coverage question (`project_validator/questions/coverage.py`) answers per language and granularity; the
     policy (`project_validator/policy.py`) requires branch coverage, or the finest granularity a known tool can
     measure, and reports path coverage as a bonus. An unknown answer is an error, naming what was not read
     (see Policy).
   - `--answers` prints the answers. C and C++ coverage tools stay in the C/C++ profile (`c_cpp/coverage.py`) until
     step 5 shares them with Fortran.

   **3½. Foundations: structure and settings as facts, and the query layer.** Step 3 showed that without shared
   layers each question would read files and join settings in its own extractor. Before the remaining practices
   move:
   - **Structure facts** (`project_validator/facts/structure.py`): every source file with its language
     (`SourceFile`), every build file with the languages it builds (`BuildFile`), what content probes found
     (`ContentLanguages`), and the suffixes no ecosystem accounts for. Vendored code (a `vendor`/`third_party`-style
     directory, a minified `*.min.js`) is recorded but makes no language the project's. The project map (`--map`)
     is a view over these facts, with the vendored files listed.
   - **Setting facts** (`project_validator/facts/settings.py`): a `SettingsReader` component reads one tool's
     settings from the files it reads by default and from the configuration files CI commands name
     (`--rcfile`, `-c`, `--settings`). Each file read is a `ConfigurationFile` fact; each setting a `Setting`
     (tool, dotted key, value, origin), flagged `heuristic` when matched in code (a Jest config, a Gradle script).
     Format helpers cover TOML, INI, JSON, XML and `key = value` files. A file that does not parse is an `Unknown`
     scoped to its tool, so it makes unknown only the answers that depend on that tool.
   - **Queries** (`Facts`): indexed by kind, with `where(kind, **fields)`, `settings(tool, paths=…)`,
     `setting(tool, key, paths=…)`, `configured(tool, paths)` (the first file with the tool's settings) and
     `first_file(reader, paths)` (the first file that exists).
   - **Extraction stages** (`Context.facts`): structure, then CI and command expansion, then settings (which
     need the commands that name configuration files), then the tools those commands run.
   - **Coverage, rebuilt on them**: coverage tools are pure functions of a command and the facts; none reads a
     file. Each declares the settings tools it `reads`, which scopes the unknowns that matter to its answers.
   - **Questions are components** (`Question` in `project_validator/questions`), found like the others, so
     `--answers` lists whatever questions exist.

   **3¾. One tool model, and units.** So that no practice builds its own copy of the machinery, and so that
   monorepos and mixed-language projects are judged where their code is:
   - **One tool model** (`project_validator/facts/tools.py`). A `Tool` records the languages it handles and, per
     *aspect* it can provide (`coverage` now; `lint`, `format`, `analysis`, `audit`, `type-check` as practices
     move), the levels it can provide and how to ask for each. It claims commands (`claims(command, facts)`) and
     reads only facts. A claimed command is a `ToolRun`: job, tool, languages, the aspects and levels that run
     provides, the settings files it read, and its scope (its working directory). Each question reads the runs of
     its aspect; a tool that serves several practices (ruff formats and lints) is one tool with several aspects.
     Coverage is spelled with `coverage_tool` and `measured` (`project_validator/facts/coverage.py`), which only
     fill in the `coverage` aspect.
   - **One way a command runs another.** Wrappers (`sudo`, `env CC=clang`, `nice`, `emcmake`, `xvfb-run`,
     `ccache`; `project_validator/tools/wrappers.py`) are launchers like `bundle exec` and `npx`: the command they
     run is a `Launched` command of its own, with the variables they set. `resolved` only substitutes variables.
   - **One way to read a command line** (`project_validator/facts/arguments.py`): `program`, `option_values`,
     `has_option`, `short_flags`, `positional`.
   - **Units** (`Unit` facts, `project_validator/facts/structure.py`). A unit is the outermost directory with a
     build system's files (a CMake project's subdirectories and a Maven project's modules belong to it), or a
     member of a workspace a build file declares (`BuildSystem.members`: npm, yarn and bun workspaces, Cargo and
     uv workspaces, go.work). A unit's languages are those of its own sources (outside the units below it), and
     what its build files build unless they only declare a workspace; sources outside every unit belong to the
     root unit. `--map` lists the units.
   - **Questions answer per language per unit.** A run covers its working directory, what is below it, and the
     unit it is in, so a run from the root covers every unit, and a run in `packages/a` covers only that package.
     A project with one unit is judged as before. In a monorepo, findings name the unit (`packages/b: no branch
     coverage …`); in a mixed-language project each language is judged in the units that have it (a C++ project
     with Python bindings in `python/` needs Python coverage there).
4. **The remaining practices**, one at a time, each deleting its rule type from `rules.py`. Each becomes settings
   readers, an aspect of the shared `Tool` model, a question answered per language per unit, and a policy.
5. **Shared build systems, toolchains and tools**: CMake, Meson, MSBuild, Gradle and Xcode, and the GCC, Clang and
   MSVC flag knowledge, leave the C/C++ profile; lizard, llvm-cov, gcov and osv-scanner become shared tools.
6. **Profiles shrink** to language recognition and the language's own tools; `rules.py` and the per-practice
   dispatch are removed.
7. **Proof**: add Fortran using only extractors and a recognition module.

`--facts` and `--answers` expose the database and the answers.
