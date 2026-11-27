# The leaderboard

An opt-in list of open-source projects. Every night, each project with a new commit is scored by the latest validator
with `--score` (see [docs/score.md](../docs/score.md)), every project is scored each week, and the results are
published to the [project site](https://cpp-best-practices.github.io/project_validator/leaderboard/):
- one board, with tabs per language, per kind and per size;
- a page per project, with its history and next steps, and its full HTML report;
- a badge per project.

The design is upstream issue #295.

Boards rank by the score: **100% means every quality gate that applies to the project is in place**, and
complementary tools earn extra credit above it. The level breaks ties.

Projects are also ranked against their own kind and size: the tabs filter the board, and the ranks count within what
they show.
- **Kind** is what the entry declares: a `library`, an `application` or a `tool`.
- **Size** is the product's lines of code, as the validator counts them (tests, tooling, vendored code and data
  formats apart): small under 10,000 lines, medium under 100,000, large above.
Every project is scored by the same validator version on the same night, and the page prints the scoring version. The
score measures tooling coverage, not code quality. The board is a showcase, not a wall of shame.

## Joining

Open a pull request that adds an entry to [`projects.toml`](projects.toml):

```toml
[[project]]
name = "owner/repo"            # on GitHub
language = "Rust"              # the board: an ecosystem label of the support matrix
kind = "library"               # library, application or tool
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

The seed entries (`consent = "seed"`) are well-known projects listed without asking, one per language, labelled as
seeds until a maintainer confirms them. Only the seed list is seeded: an entry anyone else adds needs its maintainers'
consent, and the check fails a new entry that says `consent = "seed"`.

## Leaving

Maintainers can remove their project at any time, seed or not:
- [open a removal
  request](https://github.com/cpp-best-practices/project_validator/issues/new?template=leaderboard-removal.yml), and it
  is removed with no questions asked;
- or open a pull request that deletes the entry from `projects.toml`.

Its pages, badge and history leave the site with the next run.

The `leaderboard-check` workflow checks each entry the pull request adds or changes:
- it is a public, unarchived repository;
- its licence is one GitHub recognises as OSI-approved;
- it is no larger than 2 GB;
- its language is a known board, and its kind a known kind;
- it has consent (a link, never `"seed"` for an entry the seed list did not hold);
- it is not already listed.

It then scores the project. The `leaderboard-comment` workflow posts the preview on the pull request: the score,
the level, and the top next steps, so the submitter sees where the project will land.

## Every night

The `leaderboard` workflow runs at 03:17 UTC. On weeknights and Saturdays it scores only the projects with
something new: a commit at the head of the branch since the last score (asked with `git ls-remote`), no result yet,
or a result of an earlier score version. On Sundays, and on demand, it scores every project, so that the validator's
own changes reach them all. A night with nothing new records nothing.

1. **Score.** One job per project to score. Each job:
   - shallow-clones the head of the branch;
   - runs every check with `--allow-unknown`, recording how many checks needed it, which are validator gaps;
   - scores the project.

   These jobs have a read-only token and no secrets. Evaluating an untrusted repository is safe, because the validator
   only parses build files and never runs the project's code. `--build` stays off. A project that can not be fetched
   is recorded, unscored, with why.
2. **Record.** Adds the night to the `leaderboard-data` branch:
   - `latest/` holds each project's last full results;
   - `previous/` holds the ones before those;
   - `reports/` holds each project's full HTML report, tonight's only;
   - `history/` holds one line per night per project.

   The branch is one commit, replaced each night, so the reports never grow its history; `history/` keeps every
   night's numbers. This is the only job that can write, and it writes only to that branch.
3. **Publish.** Calls the `pages` workflow, which builds the documentation site with the leaderboard
   (`tests/build_site.py --leaderboard DATA`) and deploys it.

A project whose score changes without a new commit was changed by the validator. Its "last change" says so. A crash, or
a check judged only with `--allow-unknown`, on a leaderboard project is a validator bug to file, just as the corpus is
used.

## Running it locally

```sh
python -m leaderboard matrix --changed out/data             # the projects with something new since out/data
python -m leaderboard evaluate out/results                  # every project (and its HTML report); or: ... uber/h3
python -m leaderboard record out/results out/data --date 2026-11-18
python tests/build_site.py out/site --leaderboard out/data  # the site, leaderboard included
python -m leaderboard check --base old-projects.toml --out preview.md
```
