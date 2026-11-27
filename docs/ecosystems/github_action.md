# GitHub Action

Learn more: [GitHub
Action](https://docs.github.com/en/actions/sharing-automations/creating-actions/about-custom-actions).

A format, recognised by content: a repository whose product is a reusable action has `action.yml` (or `action.yaml`) at
its root; one in a subdirectory is a local action of the repository's own workflows and makes no action repository. Nor
does an action beside another package at the root: a Python, Rust, Lua, Ruby, Java, .NET or C/C++ project's manifest
(`pyproject.toml`, `Cargo.toml`, a rockspec, a gemspec, `CMakeLists.txt`, ...) or a workspace of packages
(`pnpm-workspace.yaml`, `lerna.json`, a `package.json` with `workspaces`). That package is the product and the action a
convenience beside it (psf/black's, lunarmodules/busted's, graphql-inspector's), so none of this is asked of it. A
JavaScript action's own `package.json` and a Docker action's `go.mod` are the action's. The definition is YAML, the Data
format's, and a JavaScript or Docker action's code is judged by its own profile beside it. Every repository's workflows
are held to `ci-lint` and `action-pinning` already; this profile asks more of one whose product is an action.

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
description, branding and `runs.using` on a supported runtime is `packaging`'s (#30). A self-test on several OSes is
the action's code's platform axis: a JavaScript action's self-test runs on the Node its `runs.using` names, counted by
the JavaScript profile's `platform-matrix`; the format itself has no toolchain to carry one. The other checks have no
tool for an action and are skipped.
