"""The GitHub Actions known to run none of the project's code (upstream #273): the curated list.

A job whose only work is an action of another repository that the validator does not read may run any tool, so what it
runs is unknown (an error under --strict) until --fetch-remote reads its action.yml. Most such actions do nothing of
the kind: they label, comment, merge, release, notify or harden the runner, through GitHub's API or the runner alone.
Those are listed here, by what they do, so that their jobs are known to run nothing the checks look for.

**To add an action:** put its `owner/repo` (or `owner/repo/path` for one action of a repository holding several) in the
group that says what it does, in alphabetical order, lower case. An entry covers the actions under its path too
(`mitchellh/vouch` covers `mitchellh/vouch/action/check-pr`). An action belongs here only when it runs none of the
project's code or tools: one that builds, tests, lints, formats or spell-checks the project, or runs a command it is
given (`nick-fields/retry`), does not, and is better modelled as an `Action` with the commands it runs.

The list is data in code for now; upstream #440 moves it, with the other policy tables, into a configuration file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InertGroup:
    """Actions that run none of the project's code, and what they do instead."""

    does: str
    actions: tuple[str, ...]


# The owners of GitHub's own actions (checkout, caches, artifacts, Pages, CodeQL): none runs a tool of the project's
# that the validator does not know.
OFFICIAL_OWNERS = ("actions/", "github/")

INERT_ACTIONS = (
    InertGroup(
        "harden the runner or score the repository's settings",
        ("ossf/scorecard-action", "step-security/harden-runner"),
    ),
    InertGroup(
        "decide which jobs run, or sum up their results",
        ("dorny/paths-filter", "fkirc/skip-duplicate-actions", "re-actors/alls-green", "tj-actions/changed-files"),
    ),
    InertGroup(
        "label, comment on, lock or close issues and pull requests",
        (
            "actions-ecosystem/action-remove-labels",
            "andymckay/labeler",
            "codelytv/pr-size-labeler",
            "dessant/lock-threads",
            "dessant/support-requests",
            "eps1lon/actions-label-merge-conflict",
            "homebrew/actions/create-or-update-issue",
            "hustcer/milestone-action",
            "imjohnbo/gh-polls-bot-action",
            "ldez/no-blank-issue",
            "lee-dohm/no-response",
            "linuxserver/github-workflows/.github/actions/first-interaction",
            "marocchino/sticky-pull-request-comment",
            "mondeja/remove-labels-gh-action",
            "mschilde/auto-label-merge-conflicts",
            "peter-evans/create-or-update-comment",
            "peter-evans/find-comment",
            "redhat-plumbers-in-action/advanced-issue-labeler",
            "srvaroa/labeler",
            "stefanbuck/github-issue-parser",
            "thomasjpfan/labeler",
        ),
    ),
    InertGroup(
        "check a pull request's title, labels, changelog entry, files or commit messages, not its code",
        (
            "amannn/action-semantic-pull-request",
            "commit-check/commit-check-action",
            "crate-ci/committed",
            "dangoslen/changelog-enforcer",
            "fastify/action-pr-title",
            "gregsdennis/dependencies-action",
            "homebrew/actions/check-commit-format",
            "ljharb/require-allow-edits",
            "mheap/github-action-required-labels",
            "morrisoncole/pr-lint-action",
            "tarides/changelog-check-action",
            "thehanimo/pr-title-checker",
            "xalvarez/prevent-file-change-action",
        ),
    ),
    InertGroup(
        "approve, merge, update, back-port or open pull requests",
        (
            "ahmadnassri/action-dependabot-auto-merge",
            "cachix/git-blame-auto-reviewer",
            "chinthakagodawita/autoupdate",
            "fastify/github-action-merge-dependabot",
            "hmarr/auto-approve-action",
            "korthout/backport-action",
            "mic92/auto-merge",
            "oss-docs-tools/code-owner-self-merge",
            "pascalgn/automerge-action",
            "peter-evans/create-pull-request",
            "peter-evans/enable-pull-request-automerge",
            "prometheus/promci/approve_workflows",
            "tibdex/backport",
        ),
    ),
    InertGroup(
        "dispatch events, call GitHub's API, or manage contributors and tokens",
        (
            "astral-sh/github-actions/simple-token-service",
            "betahuhn/repo-file-sync-action",
            "contributor-assistant/github-action",
            "jamesives/github-sponsors-readme-action",
            "liquibase/build-logic/.github/actions/dispatch-and-wait",
            "mitchellh/vouch",
            "octokit/graphql-action",
            "octokit/request-action",
            "peter-evans/repository-dispatch",
            "peter-evans/slash-command-dispatch",
            "starship/crowdin-pretranslate-action",
            "tarides/pr-number-action",
        ),
    ),
    InertGroup(
        "tag, draft or publish a release of what earlier steps built, or sign it",
        (
            "actions-r-us/actions-tagger",
            "andelf/nightly-release",
            "astral-sh/github-actions/sign-macos",
            "astral-sh/github-actions/sign-windows",
            "christian-korneck/update-container-description-action",
            "endbug/latest-tag",
            "googleapis/release-please-action",
            "homebrew/actions/bump-packages",
            "juliaregistries/tagbot",
            "mislav/bump-homebrew-formula-action",
            "ncipollo/release-action",
            "peaceiris/actions-gh-pages",
            "pypa/gh-action-pypi-publish",
            "release-drafter/release-drafter",
            "scientific-python/upload-nightly-action",
            "signpath/github-action-submit-signing-request",
            "vedantmgoyal2009/winget-releaser",
            "vedantmgoyal9/winget-releaser",
        ),
    ),
    InertGroup(
        "upload or report results that earlier steps produced (coverage, test reports, artifacts)",
        (
            "andremiras/coveralls-python-action",
            "c-hive/gha-remove-artifacts",
            "codecov/codecov-action",
            "coverallsapp/github-action",
            "dawidd6/action-download-artifact",
            "dorny/test-reporter",
            "enricomi/publish-unit-test-result-action",
            "py-cov-action/python-coverage-comment-action",
            "scientific-python/circleci-artifacts-redirector-action",
            "shogo82148/actions-goveralls",
        ),
    ),
    InertGroup(
        "notify a chat",
        ("asyncapi/.github/.github/actions/slackify-markdown", "rtcamp/action-slack-notify"),
    ),
    InertGroup(
        "set up the runner: install a toolchain or dependencies without running them, cache, configure git or a cloud",
        (
            "aminya/setup-cpp",
            "homebrew/actions/git-user-config",
            "homebrew/actions/setup-homebrew",
            "liquibase/build-logic/.github/actions/setup-aws-vault",
            "ljharb/actions/node/matrix",
            "ocaml-dune/setup-dune",
            "posit-dev/setup-air",
            "r-hub/actions/checkout",
            "r-hub/actions/platform-info",
            "r-hub/actions/setup",
            "r-hub/actions/setup-deps",
            "swatinem/rust-cache",
        ),
    ),
    InertGroup(
        "verify the checksum of a committed build tool",
        ("gradle/actions/wrapper-validation",),
    ),
)


def inert(repository: str) -> bool:
    """Whether the action of `repository` (`owner/repo[/path]`, without its `@ref`) is known to run none of the
    project's code: one of GitHub's own, or one listed here (or under a listed path)."""
    name = repository.lower()
    if name.startswith(OFFICIAL_OWNERS):
        return True
    return any(name == listed or name.startswith(f"{listed}/") for group in INERT_ACTIONS for listed in group.actions)


__all__ = ["INERT_ACTIONS", "OFFICIAL_OWNERS", "InertGroup", "inert"]
