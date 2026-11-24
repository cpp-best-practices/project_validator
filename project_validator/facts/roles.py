"""Roles: what the code at a path is for (the product, its tests, examples, docs, tooling, benchmarks, templates,
or other projects' vendored code), told by the directories it is in. Shared by the structure facts and the settings
readers, which skip vendored projects' configuration. A role names code (`--auxiliary tooling`), it judges none:
every role but `vendored` is the product's until named."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Code the project carries but does not write: minified bundles, and the directories that hold other projects' code.
_MINIFIED = re.compile(r"[.-]min\.[^.]+$")
VENDOR_DIRECTORIES = (
    "third_party",
    "third-party",
    "thirdparty",
    "3rdparty",
    "external",
    "extern",
    "vendor",
    "vendored",
    "deps",
)
# The role of the code below a directory with one of these names (see `role`).
_ROLES = {
    **dict.fromkeys(VENDOR_DIRECTORIES, "vendored"),
    # `t` and `xt` are Perl's (its tests, and its author tests); a playground holds projects a test suite runs
    # against (vite's), and `inputs` a test suite's input files (json-fortran's files/inputs/).
    **dict.fromkeys(
        ("test", "tests", "testing", "testdata", "spec", "specs", "__tests__", "fixtures", "t", "xt"), "test"
    ),
    # Flutter's integration tests (phoenix's too).
    **dict.fromkeys(("playground", "playgrounds", "inputs", "integration_test"), "test"),
    **dict.fromkeys(
        ("fuzz", "fuzzing", "fuzz_test", "fuzz_tests", "fuzztest", "stress", "stress-test", "stress-tests"), "test"
    ),
    # rust-lang/book's `listings/` are the book's example programs.
    **dict.fromkeys(("example", "examples", "sample", "samples", "demo", "demos", "listings"), "example"),
    **dict.fromkeys(("doc", "docs", "documentation", "website"), "docs"),
    # `hack/` is the Kubernetes projects' name for maintainer scripts, `tool/` Dart's; `build_tools/` scikit-learn's,
    # `_tools/` deno's. `vendor-bin/` holds the tools bamarni/composer-bin-plugin installs, each a Composer project
    # (guzzle).
    **dict.fromkeys(
        ("tool", "tools", "tooling", "scripts", "hack", "build_tools", "build-tools", "_tools", "vendor-bin"), "tooling"
    ),
    # The editor integrations a tool ships (perl-code-tidyall's `etc/editors/`, dune's); not `editor/`, an editor's
    # own code.
    **dict.fromkeys(("editors", "editor-integration"), "tooling"),
    # An IDE's alternative build beside the project's own (json-fortran's hand-made .sln and .vfproj files).
    "visual_studio": "tooling",
    **dict.fromkeys(("bench", "benches", "benchmark", "benchmarks"), "benchmark"),
    # Files rendered before they are read (a Helm chart's manifests, Jinja pages, the projects a blueprint
    # generates): not well formed as they are.
    **dict.fromkeys(("template", "templates", "blueprint", "blueprints"), "template"),
}
# Names that tell a role at the top of the project only: the scripts CI runs (`ci/`), cli's `script/` and the .NET
# Arcade SDK's `eng/`. Deeper, a directory so named is code of its own (graphql-inspector's `packages/ci`, a Helm
# chart's `ci/` test values).
_TOP_LEVEL_ROLES = dict.fromkeys(("ci", "script", "eng"), "tooling")
# The roles a directory's name tells by its first or last word (`tests-build`, `integration_test`, `clap_bench`,
# `flutter_http_example`, `example_packages`). A last word `test` does not: a library for testing is a product
# (bloc's `bloc_test`), and Racket's `foo-test` packages are told by what they say.
_WORDS = {
    "tests": "test",
    **dict.fromkeys(("example", "examples"), "example"),
    **dict.fromkeys(("bench", "benchmark", "benchmarks"), "benchmark"),
}
_WORD_BREAK = re.compile(r"[-_]")
# The roles `--auxiliary` may name as not the product's (see `project_validator.facts.auxiliary`); vendored code is
# never judged, named or not.
AUXILIARY = frozenset({"test", "example", "docs", "tooling", "benchmark"})
# The roles of units that are not the product's (see `project_validator.judging`): the auxiliary ones, and a
# template of a project (a generator's scaffold, fluentd's templates/new_gem).
AUXILIARY_UNITS = AUXILIARY | {"template"}


# Directories that hold a unit's sources: below them, directory names are the code's own (`com/example/App.java`),
# but for the ones only tests and their data are kept in (`src/test/resources`, `pkg/x/testdata`).
_SOURCE_ROOTS = frozenset({"src", "lib", "source", "sources", "main", "include", "pkg", "internal", "app"})
_TESTS_BELOW_SOURCE_ROOTS = frozenset({"test", "tests", "testdata", "test-data", "test_data", "__tests__", "fixtures"})


# Directories of a test suite's data: the projects in them are inputs to the tests, not projects of the repository.
_FIXTURE_DIRECTORIES = frozenset({"fixtures", "testdata", "test-data", "test_data", "inputs"})


def fixture_data(path: str) -> bool:
    """Whether `path` is below a directory of test data (`tests/fixtures/`, `pkg/x/testdata/`)."""
    return any(part.lower() in _FIXTURE_DIRECTORIES for part in PurePosixPath(path).parts)


def _named_role(part: str) -> str | None:
    """The role a directory's name tells (`tests`, `integration-tests`, `tests-build`, `examples`, `foo_bench`), if
    any."""
    if part in _ROLES:
        return _ROLES[part]
    words = _WORD_BREAK.split(part)
    if len(words) < 2:
        return None
    first = "test" if words[0] == "test" else _WORDS.get(words[0])
    return first or _WORDS.get(words[-1])


def _vendored(posix: PurePosixPath, parts: list[str], directory: bool) -> bool:
    return _in_vendor_directory(parts) or (not directory and bool(_MINIFIED.search(posix.name)))


def _in_vendor_directory(parts: list[str]) -> bool:
    """Whether a vendor directory holds the path, outside a test suite's directory: there, a directory named
    `external` or `vendor` holds tests of external packages or of vendoring (typed-racket's, dune's: upstream
    #188)."""
    for part in parts:
        if _ROLES.get(part) == "vendored":
            return True
        if _named_role(part) == "test" or not {"test", "tests"}.isdisjoint(_WORD_BREAK.split(part)):
            return False
    return False


def role(path: str, *, directory: bool = False) -> str:
    """What the code at `path` is for: `vendored` code of other projects (below a vendor directory outside a test
    suite's, or a minified bundle), else by the outermost directory that tells, above any source root (`src`,
    `lib`): the `product`, its `test`s (test fixtures, fuzz and stress tests too), an `example`, `docs`, `tooling`, a
    `benchmark` or a `template`; below a source root only a test directory tells (`src/test/resources`). A
    directory's own name tells first, below a source root too (`internal/tools`)."""
    posix = PurePosixPath(path)
    parts = [part.lower() for part in (posix.parts if directory else posix.parts[:-1])]
    if _vendored(posix, parts, directory):
        return "vendored"
    # A directory that is a unit of its own is told by its own name first (`internal/tools`, a Go tools module).
    if directory and parts and (own := _named_role(parts[-1])):
        return own
    if parts and parts[0] in _TOP_LEVEL_ROLES:
        return _TOP_LEVEL_ROLES[parts[0]]
    for index, part in enumerate(parts):
        if part in _SOURCE_ROOTS:
            return "test" if _TESTS_BELOW_SOURCE_ROOTS.intersection(parts[index + 1 :]) else "product"
        if found := _named_role(part):
            # A vendor directory here is inside a test suite's (see `_in_vendor_directory`).
            return "test" if found == "vendored" else found
    return "product"


__all__ = ["AUXILIARY", "AUXILIARY_UNITS", "VENDOR_DIRECTORIES", "fixture_data", "role"]
