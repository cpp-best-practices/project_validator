# The tooling score (preview)

`python -m project_validator --score path/to/project` adds a score to the report. The statuses and the exit code
do not change. The score is extra output: a summary line and the top next steps in the text and markdown reports,
and a `score` object beside the results with `--format json`. The design is upstream issue #295. This is its preview,
**version 0**. It reads only what the reports already carry, so later versions will change it.

> **Level 2 · 84% complete · 137 depth**

## Cells and tiers

A **cell** is one check's result for one ecosystem in one unit: one of the `places` in `--format json`. A check of the
whole project, such as `license` or `action-pinning`, is one **project** cell. A cell of code that `--auxiliary`
names is **auxiliary**, and every other cell is **core**. A cell that skips is not applicable. A cell that errors, for
example because something could not be read, scores nothing but stays in the maximum. Hiding something never helps.

## The three numbers

**Level** is a gated tech tree. A project reaches level N when every core and project cell of the checks of levels 1
to N passes, and each of those checks ran. A warning does not complete a level.

| Level | Checks |
|---|---|
| 1, Foundations | `ci-present`, `compiler-warnings`, `warnings-as-errors`, `code-formatting`, `tests-run`, `license`, `vcs-ignore` |
| 2, Analysis | `static-analysis`, `type-checking`, `coverage`, `dependency-management`, `dependency-audit` |
| 3, Hardening | `sanitizers`, `fuzz-testing`, `mutation-testing`, `security-scanning`, `action-pinning` |
| 4, Excellence | every check ran, and every applicable cell passes, auxiliary ones included |

**Completeness** is the headline. It is covered cells over applicable cells, computed per unit and averaged across the
units. The project cells count as one more unit. A passing cell covers 1, a warning ½, anything else 0. Auxiliary cells
weigh ½. A language or unit without tooling lowers completeness, so adding code without tooling never pays.

**Depth** is the high score for projects that are already complete. Each covered cell earns points for its tools by
their rank in the cell:

| Rank in the cell | Core | Auxiliary | Project |
|---|---:|---:|---:|
| 1st tool | 10 | 5 | 10 |
| 2nd | 5 | 2 | 5 |
| 3rd | 2 | 1 | 2 |
| 4th to 6th | 1 each | 0 | 1 each |

- A covered cell earns its first rank even when the check names no tool.
- A project cell that passes without a tool earns a flat 5.
- A warning earns half.
- Depth earned in a level counts only once the levels below it are complete. The rest is reported as `locked_depth`.
- Depth is shown but never used to compare projects: the leaderboard ranks by level, then completeness.

## Next steps

Every cell that is not covered becomes an **opportunity**, with what covering it is worth:
- the completeness it adds;
- the depth it earns, which is 0 while its level is locked;
- the level it stands in the way of (`blocks`), and whether it alone does (`unlocks`).

The next level's blockers come first, lowest level first. Then come core cells before auxiliary ones, then the larger
gains.

## JSON

With `--format json --score`, the output is `{"results": [...], "score": {...}}`. `results` is exactly what
`--format json` prints without `--score`. `score` holds:
- `version` and `preview`;
- `level`, `completeness` (0 to 1), `depth` and `locked_depth`;
- `cells`, each with its check, level, ecosystem, unit, tier, status, tools, points and whether they are counted;
- `opportunities`, each with its check, ecosystem, unit, tier, status, level, completeness, depth, blocks and unlocks.

## Not yet in the preview

These parts of the design need facts the readers do not record yet:
- **Strength**, from disabled diagnostics (`-Wno-conversion`, clang-tidy `-check`, ruff `ignore`) and inline
  suppression density;
- **Advisory runs** at half points (`|| true`, `continue-on-error`);
- **Tool families**, which share a rank;
- **Verified points** from CI artefacts.

They arrive with version 1. The score measures tooling coverage, not code quality or the cost of CI.

## The leaderboard

[The leaderboard](https://cpp-best-practices.github.io/project_validator/leaderboard/) scores an opt-in list of
open-source projects every night, one board per language. See [leaderboard/README.md](../leaderboard/README.md).
