# Reporting, scoring and languages: analysis and design

Status: working design for the `ux` branch, 2026-11-19. Upstream main at 63d182b (#80, #81 and #309 merged).

## Why

The validator knows a great deal about a project: which ecosystems it found and why, its units, the code in each role,
its CI jobs and what each runs, and about 1,500 facts on a mid-size C++ project. Almost none of it reaches the reader.
The report is a flat list of check lines, the score is three numbers nobody can explain, the facts are a JSON dump,
and the site is plain Markdown pages. This design is about making all of that visible, explained and pleasant to
read, in the terminal, in a browser, and on the project site.

Two language changes come with it, because they change what every report shows: C and C++ become separate languages,
and so do JavaScript and TypeScript.

## Analysis of what there is today

Measured on `cpp-best-practices/cmake_template` (a well-tooled C++ template) and `spf13/cobra`.

### Scoring (preview v0)

1. **Three numbers, none of them a "100%".** "Level 1 · 76% complete · 100 depth" doesn't say how far from done the
   project is, or what done means. Depth is an unbounded number nobody can interpret.
2. **One incidental file decides the level.** cmake_template is held at level 1 by its devcontainer's Dockerfile,
   which has no hadolint. Its C++ tooling (clang-tidy, cppcheck, CodeQL, sanitizers, fuzzing, six-way matrix) is
   level-3 material.
3. **Test, example and script code must carry every gate**, fuzzing and mutation testing included, so 100% is out of
   reach for any project with a `tests/` directory judged as auxiliary.
4. **Extra tools are rewarded by the validator's catalogue**, not by what makes a project stronger: two formatters or
   two coverage tools earn depth.
5. **`status-badges` is scored**, though it's cosmetic.
6. **Next steps read as jargon**: "+1.0% completeness, toward Level 2".

### The terminal report

1. **Nothing says what was detected.** The ecosystems, the signals that recognised them, the units and their roles,
   the vendored code, the CI providers and jobs: all of it exists (`--map`) but only as JSON, and the default report
   never mentions it. The reader can't tell why "Docker" is judged at all.
2. **Detected roles are invisible.** The validator knows `tests/`, `examples/` and `scripts/` are test, example and
   tooling code, but says nothing until the user happens to pass `--auxiliary`.
3. **Silence while it works.** No progress during extraction; a large repository just hangs for seconds.
4. **Noise.** Twelve `[SKIP] …: not applicable to C, C++` lines; `platform-matrix` prints 40 detail lines, half of
   them duplicates; several checks pack two ecosystems into one line ("C/C++: …; Docker: …").
5. **No why.** A check name and a message, never why the practice matters or how to fix it beyond a hint.
6. **The markdown grid lists rows that apply nowhere** (`link-check`, `migration-safety` all "—").

### Facts

1. Browsable only as a 1,500-element JSON array, with no grouping, no descriptions and no links to the files.
2. One fact kind is named by its description ("libFuzzer or AFL++ fuzz targets (…)"), not a class name.

### The site

The docs site and the leaderboard are rendered Markdown with a dozen lines of CSS: no dark mode, plain tables, the
support matrix a 44-column wall, the leaderboard a bare table.

### Languages

1. **C/C++ is one ecosystem.** C and C++ are different languages with different warnings, standards, extensions,
   idioms and tooling defaults. One column hides a project that sets `-Wall -Wextra` for its C++ and nothing for its C.
   It also means every CMake project is both C and C++, because CMake's `project()` defaults to both.
2. **JavaScript/TypeScript is one ecosystem.** Type checking is the defining gate of TypeScript (`tsc --noEmit`,
   `strict`) and not a norm of JavaScript, so one column either asks JavaScript projects for type checking or lets
   TypeScript projects off it.

## Decisions

### C and C++ are separate ecosystems

- Two ecosystems, **C** and **C++**, sharing their build systems (CMake, Meson), compiler and CI knowledge.
- A language is a unit's when it has its sources. A build file alone no longer makes a project both: CMake's
  `project()` defaults say nothing about the code.
- `.h` (and `.inc`) headers belong to C++ in a unit with C++ sources, otherwise to C. A unit of headers only (a
  header-only library with `.h` files) is C unless something says C++ (`LANGUAGES CXX`, `cpp_std`, C++ standard
  flags).
- Flags are attributed per language: `CMAKE_C_FLAGS` and `$<COMPILE_LANGUAGE:C>` to C, the `CXX` forms to C++, and
  unqualified flags (`add_compile_options`, `target_compile_options`, Meson's `warning_level`) to both.
- `cxx-extensions` applies to C++ only. Every other C/C++ check applies to both, judged separately.
- Docs: `docs/ecosystems/c.md` and `cpp.md`. The leaderboard's C/C++ seed moves to its language, and the other
  language gets a seed.

### JavaScript and TypeScript are separate ecosystems

Different concerns, so yes:

- **TypeScript**: `.ts`, `.tsx`, `.mts`, `.cts`, `.d.ts`, or a `tsconfig.json`. Type checking applies (tsc, vue-tsc,
  or a bundler's type check).
- **JavaScript**: `.js`, `.jsx`, `.mjs`, `.cjs`. Type checking doesn't apply: it isn't the ecosystem's norm.
- Both share package.json reading, package managers, test runners, ESLint, Prettier, Biome and dependency audit.
- A TypeScript project's JavaScript tooling configuration (`*.config.js`, `.eslintrc.js`, `gulpfile.js`) doesn't
  make it a JavaScript project. Those files are configuration, not sources.
- The leaderboard's seed (Compiler Explorer) is TypeScript; JavaScript gets a seed.

### Score v1: 100% means every applicable gate is in place

The design proposed on #295 after the preview:

- **Slots.** One per gate that applies, per language, per unit, plus the project-wide gates once.
- **Fill.** Pass 1, warn ½, fail and error 0, skip not a slot. Auxiliary slots weigh ½.
- **Auxiliary code carries fewer gates.** Formatting, static analysis, type checking, compiler warnings, warnings as
  errors, tests run, VCS hygiene and committed artifacts apply; coverage, fuzzing, mutation, sanitizers, hardening,
  dependency audit and platform matrix don't.
- **Pooled, not averaged.** `base = 100 × filled ÷ slots`. A one-gate data folder weighs one slot.
- **Extra credit, only where tools complement each other:** static analysis, security scanning, dependency audit,
  fuzzing, sanitizers, type checking, compiler warnings (more compilers). The second distinct tool earns +¼ of a
  slot, the third +⅒; tools of one family (ruff and flake8; golangci-lint and its bundled linters) count once.
- **Held until 100%.** `score = base` below 100, `100 + extra` once every slot is filled; the held extra credit is
  shown.
- `status-badges` is reported but not scored.
- **Levels stay, as milestones**: 1 Foundations, 2 Analysis, 3 Hardening, 4 Complete (= 100%). Same gating rule as
  v0, auxiliary slots excluded from levels 1 to 3.
- **Next steps in plain words**: "Run fuzz tests in CI (C++, root): +4 points, needed for Analysis".

### One analysis, many views

All output comes from one `Analysis` value: the project, the structure (map), the facts, the reports, the score, the
options, the timings and the validator's version. Every renderer takes it:

| View | How | Needs |
|---|---|---|
| plain text | default without a terminal or rich | nothing |
| console | default in a terminal with rich | `[pretty]`: rich |
| markdown | `--format markdown` | nothing |
| JSON | `--format json` | nothing |
| HTML report | `--format html`, or `--html FILE` beside any format | nothing |
| TUI | `--tui` | `[tui]`: textual |

Extraction reports progress through an observer: each stage starting and finishing, with what it found. The console
shows it live on stderr; the TUI shows it on its loading screen.

### The console report

In order:

1. **Header**: project, path, commit if it's a git checkout.
2. **Detected**: each ecosystem with the signals that recognised it; the units (directory, role, languages, build
   systems); code in each detected role, with the `--auxiliary` flag that would judge it as auxiliary; vendored and
   unrecognised files; CI providers and job count. And how it was read: each extraction stage with its counts.
3. **Results**, grouped by level (Foundations, Analysis, Hardening, then Hygiene and Project). One line per check,
   then one line per language when they differ. Details deduplicated and capped (`--verbose` shows all). Skipped and
   inapplicable checks are counted, not listed (`--verbose` lists them).
4. **Score**: a bar to 100%, the milestone, the slots filled, held extra credit, and the top next steps.

`--explain CHECK` prints what a check looks for, why it matters, what passes, and the tools it recognises per
language. Each check gains a `rationale`: one or two sentences on why the practice matters.

Plain text keeps its `[STATUS] check: message` lines (greppable in CI logs), gains the Detected section, and
deduplicates details.

### The HTML report

One self-contained file: inline CSS and JavaScript, no network, light and dark themes, printable.

- **Summary**: a score ring, the milestone, status counts, the top next steps.
- **Detected project**: ecosystems and their signals, units, roles, vendored code, CI jobs with OS, compilers and
  configurations, and how it was read.
- **Results matrix**: checks by language, colour-coded, each cell linking to its finding.
- **Findings**: each check's result per place, with details, the hint, the rationale and the tools.
- **Facts browser**: every fact, filterable by kind and searchable, grouped by kind with each kind's description, and
  each origin linking to the file on GitHub when the remote is known.
- **Run**: validator version, options, timings.

### The TUI

`--tui` (textual): a tree on the left (Overview, Detected, Units, Results by status, Score, Facts by kind), detail on
the right, `/` to search, `q` to quit. It shows extraction progress while it loads.

### The site's design

One design system, shared by the HTML report, the docs site and the leaderboard: a stylesheet in the package, with
light and dark themes and a header with navigation.

- **Docs site**: styled pages; the support matrix with sticky headers, coloured cells and a language filter.
- **Leaderboard**: score bars, milestone chips, per-language tabs and sparklines. Each project page links its full
  nightly HTML report, which the nightly job now writes.

### Optional dependencies

`[pretty]` = rich, `[tui]` = textual (and rich), `[all]` = both. The HTML report needs nothing. CI's test and coverage
requirements install both, so their code is tested and covered; the tests without them still run.

## Order of work

1. C and C++ split.
2. JavaScript and TypeScript split.
3. Score v1.
4. The `Analysis` model, progress events, check rationales, `--explain`.
5. The console report (rich) and plain text improvements.
6. The HTML report.
7. The TUI.
8. The site and leaderboard redesign, with nightly HTML reports.

Each step is test-first, with every gate green, committed separately.
