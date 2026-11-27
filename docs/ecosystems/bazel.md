# Bazel

Learn more: [Bazel](https://bazel.build/).

A format: the project's Bazel files (`BUILD.bazel`, `MODULE.bazel`, `WORKSPACE`, `WORKSPACE.bzlmod` and `*.bzl`
macros), Starlark judged beside the language it builds. Bazel as the build system of C, C++ and Swift (its test
rules, compilation modes and `.bazelrc` options) is read for those profiles; what is asked of the files themselves is
hygiene. A CI job works with them when it runs `bazel`, `bazelisk` or buildifier. A file named only `BUILD` is not
taken for Bazel's, since Pants names its build files so too; `.bazelrc` files hold Bazel's options, not Starlark, and
add nothing to format.

## `code-formatting`

buildifier, in `-mode=check` or `-mode=diff` (`-d`), which fail on a file it would change; with no mode, or
`-mode=fix`, it rewrites the files, which enforces the style with a later `git diff --exit-code`. Its style is fixed;
`.buildifier.json` sets which files it reads as which type and which warnings it reports. keith/pre-commit-buildifier's
`buildifier` hook counts where CI runs it.

## `static-analysis`

buildifier's linter: `-lint=warn`, or `-lint=fix`, which fixes what it can and reports the rest. Both of
keith/pre-commit-buildifier's hooks (`buildifier`, `buildifier-lint`) lint where CI runs them.

## Not judged

Bazel files are not a program of their own: tests, coverage and the compiled-language checks belong to the language
they build. The other checks have no tool for Bazel files and are skipped.
