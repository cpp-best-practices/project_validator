# GitHub Action

A format, recognised by content: a repository whose product is a reusable action has `action.yml` (or `action.yaml`)
at its root; one in a subdirectory is a local action of the repository's own workflows and makes no action
repository. The definition is YAML, the Data format's, and a JavaScript or Docker action's code is judged by its own
profile beside it. Every repository's workflows are held to `ci-lint` and `action-pinning` already; this profile asks
more of one whose product is an action.

## `tests-run`

A workflow of the repository uses the action itself (`uses: ./`), running it from the checkout: the self-test. The
workflows that do are what defines the tests.

## `static-analysis`

actionlint lints the workflows (`actionlint`, or `rhysd/actionlint`), with its settings in
`.github/actionlint.yaml`.

## `security-scanning`

zizmor audits the workflows and the action's definition (`zizmor .`, or `zizmorcore/zizmor-action`; settings in
`zizmor.yml` or `.github/zizmor.yml`): template injection, unpinned actions, credentials a checkout persists.

## Not judged

Every `uses:` pinned to a commit with no tag allowance is `action-pinning`'s to ask; `action.yml`'s name,
description, branding and `runs.using` on a supported runtime is `packaging`'s (#30); a self-test on more than one OS
would be a platform axis, which a format has no toolchain to carry. The other checks have no tool for an action and
are skipped.
