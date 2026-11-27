"""Bazel: the project's Bazel files (`BUILD.bazel`, `MODULE.bazel`, `WORKSPACE`, `*.bzl` macros), Starlark, a format
judged beside the language they build. Bazel as a build system is read by `project_validator.build_systems.bazel`
for the C, C++ and Swift profiles; what is asked of the files here is hygiene: buildifier formats them
(`code-formatting`) and lints them (`static-analysis`). A file named only `BUILD` says no Bazel: Pants names its
build files so too."""

from __future__ import annotations

from project_validator.ecosystems.model import Ecosystem
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.formatting import Enforcement, format_tool, formatted
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import Run, combined, defined_by, when

BAZEL = "Bazel"
BAZEL_ONLY = frozenset({BAZEL})

BAZEL_ECOSYSTEM = Ecosystem(
    label="Bazel",
    links={"Bazel": "https://bazel.build/"},
    kind="format",
    languages=BAZEL_ONLY,
    source_suffixes={".bazel": BAZEL, ".bzl": BAZEL, ".bzlmod": BAZEL},
    source_names={"WORKSPACE": BAZEL},
    # rc files hold options, not Starlark: Bazel's, adding nothing to format.
    ambiguous_suffixes={".bazelrc": None},
    ci_programs=(("bazel",), ("bazelisk",), ("buildifier",)),
)

# buildifier's style is fixed; `.buildifier.json` sets which files it reads as which type and which warnings it
# reports.
BUILDIFIER_SETTINGS = file_reader("buildifier", (".buildifier.json",))
_BUILDIFIER = ("buildifier",)


def _last(argv: tuple[str, ...], *names: str) -> str | None:
    values = option_values(argv, *names)
    return values[-1] if values else None


def _formats(command: Command, facts: Facts) -> Run | None:
    """buildifier's `-mode=check` and `-mode=diff` (`-d`) fail on a file it would change; with no mode, or
    `-mode=fix`, it rewrites them."""
    argv = resolved(command)
    if starts_with(argv, _BUILDIFIER) is None:
        return None
    mode = _last(argv, "-mode", "--mode") or ("diff" if "-d" in argv[1:] else "fix")
    return formatted(command, facts, checks=mode in {"check", "diff"}, applies=mode == "fix")


def _lints(command: Command) -> bool:
    """buildifier's linter runs with `-lint=warn`, and with `-lint=fix`, which reports what it cannot fix."""
    argv = resolved(command)
    return starts_with(argv, _BUILDIFIER) is not None and _last(argv, "-lint", "--lint") in {"warn", "fix"}


# One program that formats and lints, as RuboCop does.
BUILDIFIER = combined(
    format_tool(
        name="buildifier",
        languages=BAZEL_ONLY,
        can={Enforcement.CHECK: "buildifier -mode=check -r .", Enforcement.APPLY: "buildifier -r ."},
        formats=_formats,
        style=defined_by(files=(BUILDIFIER_SETTINGS.name,)),
    ),
    analyzer(
        name="buildifier",
        languages=BAZEL_ONLY,
        how="buildifier -lint=warn -mode=check -r .",
        analyses=when(_lints, analysed),
        rules=defined_by(files=(BUILDIFIER_SETTINGS.name,)),
    ),
)
