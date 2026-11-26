# The tooling score

The console and HTML reports always show the score; `python -m project_validator --score path/to/project` adds it to
the plain text, markdown and JSON outputs too. The statuses and the exit code do not change. The design is upstream
issue #295; this is **version 1**.

> **87% · Level 2 Analysis · 41 of 47 gates in place**

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
- A language the validator has no tools for adds no slot for the gates it can not judge: that gap is the validator's to
  fix, not the project's.

So 100% is reachable, and means exactly that: every gate that applies to each part of the project is in place. Size
weights only the percent: the levels still ask every language for every gate of theirs.

## Extra credit

Some gates find more with each tool: two static analysers, a scanner beside CodeQL, a second fuzzing engine, more
sanitizers, a second type checker. In those gates (`static-analysis`, `security-scanning`, `dependency-audit`,
`fuzz-testing`, `sanitizers`, `type-checking`, `compiler-warnings`), the second distinct tool in a slot earns a
quarter of a slot more, and the third a tenth. Tools of one family count once: ruff and flake8, or golangci-lint and
the linters it bundles. Two formatters, or two coverage tools, earn nothing: they do not make a project stronger.

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

## JSON

With `--format json --score`, the output is `{"format": "results", "version": "1", "results": [...], "score": {...}}`.
`results` is exactly what `--format json` prints without `--score`. `score` holds:

- `version`, `percent` (with any extra credit), `base` (the share of slots filled), `extra` and `held`;
- `level` and `level_name`, `filled` and `slots`, and the `summary` line;
- `breakdown`: each language's filled slots and slots (`""` for the whole project's own gates);
- `cells`: each slot's check, level, language, unit, tier, status, tools, weight, filled share and extra credit;
- `next_steps`: each step's check, language, unit, tier, status, level, points, `needed_for`, `completes`, the
  message found and the hint.

## What the score is not

It measures whether quality gates are in place, not the quality of the code, nor the cost of the CI. A gate that runs
but can not fail CI (`|| true`) still counts for now; reading that, and verified points from CI artefacts, are for a
later version. The score's version is printed with it, so numbers from different versions are never compared.

## The leaderboard

[The leaderboard](https://cpp-best-practices.github.io/project_validator/leaderboard/) scores an opt-in list of
open-source projects every night, ranked by this score. See [leaderboard/README.md](../leaderboard/README.md).
