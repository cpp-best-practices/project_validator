# The tooling score

The console and HTML reports always show the score; `python -m project_validator --score path/to/project` adds it to
the plain text, markdown and JSON outputs too. The statuses and the exit code do not change. The design is upstream
issue #295; this is **version 7**.

> **87% · Level 2 Analysis · 41 of 47 gates in place**

## What the score is for

The validator exists to drive a project's development towards higher quality, whether a person or an AI agent does
the work. Copy-pasted code, code no tool checks, large and complex functions, warnings turned off: each makes the code
worse, and each is something a quality gate can catch and keep out. The score counts those gates, so that the way to
raise it is to put them in place and keep them on.

That only works if the number has two properties:

- **It changes in meaningful ways as the code gets better.** A new gate, a tool turned back on, a suppression removed:
  each moves the score, in proportion to what it adds. A change that doesn't make the code better doesn't move it.
- **It is hard to game.** A tireless optimiser told to raise the number must find that the cheapest way to raise it is
  to improve the code. A gate that runs but can't fail, a check turned off, a tool nobody's code reaches: none of these
  earns what the real gate does.

This is why turning a warning off has a cost even when it is done one line at a time. If a comment like
`NOLINT(bugprone-…)` were free, a project could keep every tool "on" and silence each finding where it appears. The
gate would look in place while finding nothing. So a local suppression of a rule that finds bugs costs something,
less with a reason, never nothing, and always less than turning the rule off everywhere. The cheapest way to keep a
rule that must be off for some code is to move that code into one small, well-tested function and turn the rule off
there once. A comment that turns off a lint rule that finds no bugs, or formatting, costs nothing, but the report still
lists it.

The score measures whether the gates are in place, not the code itself. The gates are what keep the code from getting
worse.

## 100% means every gate is in place

A **slot** is one check's result for one language in one unit: one of the `places` in `--format json`. A check of the
whole project (a licence, CI, action pinning) is one slot. The score is the share of the slots that are filled:

```text
percent = 100 * filled / slots
```

| Result | Fills |
| --- | --- |
| pass | the whole slot |
| warning (configured but not enforced, or partly in place) | half |
| fail, or error | nothing, but the slot counts: hiding something never helps |
| skip (the gate does not apply) | not a slot |

- **Weighed by size** (score version 2). A language's slots weigh its share of its unit's product lines, but at least
  10%: in a Rust crate with a one-line helper script, a Shell gap costs a tenth of a Rust one, and still costs
  something. Test, tooling, example and vendored code count for no language's size, and a format's lines (YAML,
  JSON, TOML) count as a language's do. The whole project's own gates (a licence, CI) weigh one slot each.
- **Pooled.** The slots are pooled, so a folder of data files with one gate weighs its slot, not as much as the code
  with twenty.
- **Auxiliary code** (what `--auxiliary` names: tests, examples, scripts) weighs half, and is not asked for the gates
  of the product alone: coverage, fuzzing, mutation testing, sanitizers, hardening, dependency audit, the platform
  matrix, build types and security scanning.
- **Not scored:** `status-badges` is reported, but a README badge is not a quality gate.
- **Defects the validator finds itself only take points away** (score version 3). `data-wellformed`,
  `repository-hygiene`, `committed-artifacts`, `large-files` and `ci-current` pass because no defect was found, not
  because the project put a process in place, so passing they are no slot and earn nothing. Finding a defect (a file
  that does not parse, a committed build output), warning or failing, they are a slot nothing fills: it costs its
  share, keeps the project from 100%, and is a next step. **Only the processes a project puts in place earn points:**
  a CI step that checks the files (`file-soundness`, `schema-validation`), configuration that keeps outputs out
  (`vcs-ignore`), a check of CI itself (`ci-lint`).

So 100% is reachable, and means exactly that: every gate that applies to each part of the project is in place. Size
weights only the percent: the levels still ask every language for every gate of theirs.

## By language and by unit

The views break the score down by language, and, in a project of several units (a monorepo), by unit too: how much of
each part's gates is in place. The headline stays the one score of the whole project.

## Strength

A tool that is turned off counts for less (score version 4; lint rules that find no bugs weigh nothing since version
5). A tool's **strength**, from 0 to 1, is what is left after what its configuration turns off and the suppressions
written in the code:

```text
strength = max(0, 1 - the weights of what is turned off - the density of the suppressions)
```

| Turned off | Everywhere | In one file |
| --- | --- | --- |
| Everything (clang-tidy's `-*` with nothing enabled after it, ruff's `ALL`, `-w`, mypy's `ignore_errors`) | the tool counts as not run | 0.5 |
| A diagnostic that finds bugs (`bugprone-*`, clang-tidy's memory checks such as `cppcoreguidelines-pro-bounds-*`, `-Wconversion`, bugbear `B`, bandit `S`, mypy's error codes, tsconfig's strict flags), no reason given | 0.25 | 0.05 |
| The same, with a comment saying why on its line or the line above | 0.12 | 0.02 |
| Any other diagnostic: a lint rule that finds no bugs (naming, readability, line length) | 0 | 0 |

Lint rules that find no bugs weigh nothing: strength is what a tool can still find of bugs. A project that enables
every check and turns off the ones that don't apply to it (clang-tidy's `altera-*` for FPGAs, `fuchsia-*` for
Fuchsia's rules) must not count for less than one that only ever enabled a few.

clang-tidy's checks against undefined behaviour (`cppcoreguidelines-pro-bounds-*`, `pro-type-reinterpret-cast`,
`pro-type-union-access`, `hicpp-no-array-decay`, `hicpp-signed-bitwise`) find bugs for this purpose. Each flags every
use of a construct that can be undefined (an index out of bounds, an aliasing violation, a read of a union's inactive
member), not only the uses that are, so a project may turn one off on purpose; it still costs as a check that finds
bugs, and the next step to turn it back on says what it guards against. A comment naming a glob that covers a check
(`# cppcoreguidelines-pro-bounds-*: parsers index by design`) says why for each check it covers.

The weights are in `project_validator/policy/strength.toml`, and which diagnostics turn everything off or find bugs,
with what they guard against, in `project_validator/policy/diagnostics.toml`
([#440](https://github.com/cpp-best-practices/project_validator/issues/440)).

The comments in the product's code that turn rules off (`NOLINT`, `# noqa`, `# type: ignore`, `eslint-disable`,
`#[allow]`, `//nolint`, `@SuppressWarnings`, ...) weigh by the rules they name (score version 7):

| A comment that turns off | Weighs |
| --- | --- |
| Only lint rules that find no bugs (`# noqa: E501`, `NOLINT(readability-magic-numbers)`, `rubocop:disable Style/…`) | nothing; "About the project" counts them |
| A rule that finds bugs, or names none (`NOLINT(bugprone-…)`, `# noqa: F401`, a bare `# noqa`) | 0.02 per thousand lines of the tool's languages |
| The same, with text or a link after it saying why | 0.005 per thousand lines |

The comments that cost weigh at most 0.5 together, and each rule's are held below what turning that rule off weighs:
those in one file at most 0.8 of turning it off for that file, and all of them at most 0.8 of turning it off
everywhere (a comment naming no rule, of turning everything off). So one comment costs less than many, and many cost
less than turning the rule off: the cheapest way to keep a rule that must be off for some code is to move that code
into one well-tested place and turn the rule off there once. A comment naming several rules counts for each that finds
bugs. A file turned off whole (`# mypy: ignore-errors`, `/* eslint-disable */`) weighs as everything turned off for
one file.

Which rules find bugs is the same list as for the configuration, in `policy/diagnostics.toml`; eslint, golangci-lint
and RuboCop are named there for their comments alone. A tool the file doesn't name (cppcheck, Error Prone, PHPStan)
finds bugs with every rule, until its table says otherwise.

**A slot is filled as far as its strongest tool is strong** (score version 7): a gate whose clang-tidy is at 0.9
fills 0.9 of its slot, so whatever turns a tool off shows in the score, a comment as much as a configuration. **A gate
counts only when its strongest tool is at least half strong.** Below that, its slot is not filled at all, it holds its
level back, and it is a next step: turn back on what is turned off, and fix what the tool finds. A gate's extra credit
is scaled by its tools' mean strength (once: not again by how far its slot is filled). Each slot's `strength` is in
`--format json --score`.

Each diagnostic that finds bugs a tool's configuration turns off is a next step of its own, where turning it back on
restores points: `re-enable bugprone-narrowing-conversions in .clang-tidy (clang-tidy)`, and fix what the tool finds.
It is worth what it fills of its slots again, and the extra credit it restores, whether or not the gate already counts;
a small, local task that improves the code rather than adding a tool.

## Extra credit

Some gates find more with each tool: two static analysers, a scanner beside CodeQL, a second fuzzing engine, more
sanitizers, a second type checker. In those gates (`static-analysis`, `security-scanning`, `dependency-audit`,
`fuzz-testing`, `sanitizers`, `type-checking`, `compiler-warnings`), the second distinct tool in a slot earns a
quarter of a slot more, and the third a tenth. Tools of one family count once: ruff and flake8 (since score version 6),
or golangci-lint and the linters it bundles. Two formatters, or two coverage tools, earn nothing: they do not make a
project stronger.

**Extra credit is held until every slot is filled.** Below 100% it is shown but not added, so passing 100% always
means every gate is in place: `100% + extra`.

## Levels

Levels are milestones: a project reaches level N when every core and project slot of the checks of levels 1 to N
passes, and each of those checks ran. A warning does not complete a level, and auxiliary code never holds one back.

| Level | Checks |
| --- | --- |
| 1, Foundations | `ci-present`, `compiler-warnings`, `warnings-as-errors`, `code-formatting`, `tests-run`, `license`, `vcs-ignore` |
| 2, Analysis | `static-analysis`, `type-checking`, `coverage`, `dependency-management`, `dependency-audit` |
| 3, Hardening | `sanitizers`, `fuzz-testing`, `mutation-testing`, `security-scanning`, `action-pinning` |
| 4, Complete | every check ran, and every slot is filled: 100% |

## Next steps

Every slot not filled is a next step, with the points filling it is worth and, when it stands in the way of the next
level, which level. The next level's gates come first (the one that completes it first), then the lower levels, core
before auxiliary code, then the most points. Each says what was found and, when a detail says what to do, that:

```text
coverage (C++ in lib): +4.2 points, needed for Level 2 (Analysis); consider running gcovr in CI
```

`python -m project_validator --explain CHECK` says what a gate looks for, why it matters, and the tools it recognises
for each language.

## Gates

The score never changes the exit code by itself. Two opt-in floors make it: `--min-level LEVEL` (0 to 4) fails the
run unless the project reaches that level, and `--min-completeness PERCENT` (0 to 100) fails it unless at least that
share of the gates is in place. Extra credit is not completeness. A run below a floor exits 1 and says why on stderr:

```text
project_validator: score below its floor: Level 1 Foundations is below --min-level 2
```

A run narrowed by `--only` or `--skip` reaches no level past the checks it left out, so a level floor fails it. The
floors need the analysis: they cannot be given with `--facts`, `--map`, `--answers` or `--tui`.

## JSON

With `--format json --score`, the output is `{"format": "results", "version": "1", "results": [...], "score": {...}}`.
`results` is exactly what `--format json` prints without `--score`. `score` holds:

- `version`, `percent` (with any extra credit), `base` (the share of slots filled), `extra` and `held`;
- `level` and `level_name`, `filled` and `slots`, and the `summary` line;
- `breakdown`: each language's filled slots and slots (`""` for the whole project's own gates);
- `units`: each unit's filled slots and slots, the same way;
- `cells`: each slot's check, level, language, unit, tier, status, tools, weight, filled share and extra credit;
- `next_steps`: each step's check, language, unit, tier, status, level, points, `needed_for`, `completes`, the
  message found and the hint.

## What the score is not

It measures whether quality gates are in place, not the quality of the code, nor the cost of the CI. A gate that runs
but can not fail CI (`|| true`, a pipe without `pipefail`, `continue-on-error`) is a warning, and fills half its slot;
verified points from CI artefacts are for a later version. The score's version is printed with it, so numbers from
different versions are never compared.

## The leaderboard

[The leaderboard](https://cpp-best-practices.github.io/project_validator/leaderboard/) scores an opt-in list of
open-source projects every night, ranked by this score. See [leaderboard/README.md](../leaderboard/README.md).
