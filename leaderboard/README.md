# The leaderboard

An opt-in list of open-source projects. Every night, each project is scored by the latest validator with `--score`
(see [docs/score.md](../docs/score.md)), and the results are published to the
[project site](https://cpp-best-practices.github.io/project_validator/leaderboard/):
- one board, with a tab per language;
- a page per project, with its history and next steps, and its full HTML report;
- a badge per project.

The design is upstream issue #295.

Boards rank by the score: **100% means every quality gate that applies to the project is in place**, and
complementary tools earn extra credit above it. The level breaks ties.
Every project is scored by the same validator version on the same night, and the page prints the scoring version. The
score measures tooling coverage, not code quality. The board is a showcase, not a wall of shame.

## Joining

Open a pull request that adds an entry to [`projects.toml`](projects.toml):

```toml
[[project]]
name = "owner/repo"            # on GitHub
language = "Rust"              # the board: an ecosystem label of the support matrix
consent = "https://github.com/owner/repo/issues/123"   # the maintainers' approval
# optional:
# branch = "main"              # else the default branch
# auxiliary = ["scripts/"]     # as --auxiliary takes them
# exclude = ["testdata"]       # as --exclude takes them
# license = "MIT"              # when GitHub can not tell which it is
```

An entry needs the project's agreement:
- a pull request by one of its maintainers, linking to itself or to the maintainer's comment;
- or a link to their approval in an issue or comment.

Maintainers can remove their project at any time, by pull request or issue. The seed entries (`consent = "seed"`)
are labelled as seeds until a maintainer confirms them.

The `leaderboard-check` workflow checks each entry the pull request adds or changes:
- it is a public, unarchived repository;
- its licence is one GitHub recognises as OSI-approved;
- it is no larger than 2 GB;
- its language is a known board;
- it has consent;
- it is not already listed.

It then scores the project. The `leaderboard-comment` workflow posts the preview on the pull request: the score,
the level, and the top next steps, so the submitter sees where the project will land.

## Every night

The `leaderboard` workflow runs at 03:17 UTC, and on demand.

1. **Score.** One job per project. Each job:
   - shallow-clones the head of the branch;
   - runs every check with `--allow-unknown`, recording how many checks needed it, which are validator gaps;
   - scores the project.

   These jobs have a read-only token and no secrets. Evaluating an untrusted repository is safe, because the validator
   only parses build files and never runs the project's code. `--build` stays off. A project that can not be fetched
   is recorded, unscored, with why.
2. **Record.** Adds the night to the `leaderboard-data` branch:
   - `latest/` holds tonight's full results;
   - `previous/` holds the night before's;
   - `reports/` holds each project's full HTML report, tonight's only;
   - `history/` holds one line per night per project.

   The branch is one commit, replaced each night, so the reports never grow its history; `history/` keeps every
   night's numbers. This is the only job that can write, and it writes only to that branch.
3. **Publish.** Calls the `pages` workflow, which builds the documentation site with the leaderboard
   (`tests/build_site.py --leaderboard DATA`) and deploys it.

A project whose score changes overnight without a new commit was changed by the validator. Its "since last night"
says so. A crash, or a check judged only with `--allow-unknown`, on a leaderboard project is a validator bug to
file, just as the corpus is used.

## Running it locally

```sh
python -m leaderboard evaluate out/results                  # every project (and its HTML report); or: ... uber/h3
python -m leaderboard record out/results out/data --date 2026-11-18
python tests/build_site.py out/site --leaderboard out/data  # the site, leaderboard included
python -m leaderboard check --base old-projects.toml --out preview.md
```
