"""Bazel as a build system (upstream #207): a project with a `MODULE.bazel`, `WORKSPACE` or `BUILD.bazel` file builds
with Bazel. Its BUILD files (`BUILD`, `BUILD.bazel`) are read for the rules they call (`syntax`): the kinds of rule each
uses, and the test rules (`cc_test`, `swift_test`, `sh_test`, any `*_test`) it defines, which `bazel test` (or
`bazel coverage`) runs. A command's `--compilation_mode` (`-c`) is its build type: `dbg` is Debug, `opt` Release, and
the default, `fastbuild`, neither. Bazel's output directories (`bazel-bin`, `bazel-out`, `bazel-<workspace>`) are
build trees.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from project_validator.build_systems.bazel.syntax import rules
from project_validator.build_systems.model import BuildSystem
from project_validator.facts import Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.arguments import option_values
from project_validator.facts.settings import SettingsReader, unreadable
from project_validator.facts.testing import test_runner, tested
from project_validator.facts.tools import Definition, Run
from project_validator.parsing import ParseError

BAZEL_NAME = "Bazel"
_PROGRAMS = frozenset({"bazel", "bazelisk"})
# The commands that build, and so have a compilation mode.
_BUILDING = frozenset({"build", "test", "run", "coverage"})
_TESTING = frozenset({"test", "coverage"})
_MODES = {"dbg": "debug", "opt": "release"}


def bazel_command(argv: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
    """A bazel (or bazelisk) command's subcommand and the words after it, past its startup options (`--batch`); None
    for another program, or a bazel command with no subcommand."""
    if not argv or Path(argv[0]).name not in _PROGRAMS:
        return None
    for index, word in enumerate(argv[1:], start=1):
        if not word.startswith("-"):
            return word, argv[index + 1 :]
    return None


def bazel_build_types(command: Command) -> frozenset[str]:
    """The build types a bazel command builds: its last `--compilation_mode` (`-c`)."""
    found = bazel_command(resolved(command))
    if found is None or found[0] not in _BUILDING:
        return frozenset()
    modes = option_values(("bazel", *found[1]), "-c", "--compilation_mode")
    return frozenset({_MODES[modes[-1]]}) if modes and modes[-1] in _MODES else frozenset()


WORKSPACE_FILES = ("MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel")


def _is_build_tree(directory: Path) -> bool:
    """Bazel's output directories, which it links at the top of the workspace (`bazel-bin`, `bazel-<workspace>`)."""
    return directory.name.startswith("bazel-") and any((directory.parent / name).exists() for name in WORKSPACE_FILES)


BAZEL = BuildSystem(
    name=BAZEL_NAME,
    files=(*WORKSPACE_FILES, "BUILD.bazel"),
    is_build_tree=_is_build_tree,
    build_types=bazel_build_types,
)


def _read_build_file(path: str, text: str) -> Iterator[Fact]:
    """The kinds of rule a BUILD file calls, and the names of its test rules."""
    found, problems = rules(text)
    origin = Origin(path=path)
    if problems and not found:
        first = problems[0]
        yield unreadable(BAZEL_NAME, path, ParseError(first.reason, first.span.line if first.span else None))
        return
    kinds = tuple(sorted({rule.kind for rule in found if rule.kind != "load"}))
    if kinds:
        yield Setting(origin=origin, tool=BAZEL_NAME, key="rules", value=kinds)
    tests = tuple(rule.name for rule in found if rule.kind.endswith("_test") and rule.name is not None)
    if tests:
        yield Setting(origin=origin, tool=BAZEL_NAME, key="tests", value=tests)


BAZEL_BUILD_FILES = SettingsReader(name=BAZEL_NAME, files=("BUILD", "BUILD.bazel"), read=_read_build_file)


def _defined(facts: Facts) -> Iterator[str]:
    yield from (found.path for found in facts.where(Setting, tool=BAZEL_NAME, key="tests"))


def _bazel_test(command: Command, _facts: Facts) -> Run | None:
    found = bazel_command(resolved(command))
    return tested() if found is not None and found[0] in _TESTING else None


BAZEL_TEST = test_runner(
    name="bazel test",
    # The languages Bazel's own and common rules test: cc_test, swift_test, objc_test.
    languages=frozenset({"C", "C++", "Objective-C", "Objective-C++", "Swift"}),
    how="bazel test",
    runs=_bazel_test,
    tests=Definition(
        found=_defined,
        default=False,
        describe="tests defined by Bazel test rules (cc_test, swift_test, sh_test, …) in BUILD files",
    ),
    reads=(BAZEL_NAME,),
)


__all__ = [
    "BAZEL",
    "BAZEL_BUILD_FILES",
    "BAZEL_NAME",
    "BAZEL_TEST",
    "WORKSPACE_FILES",
    "bazel_build_types",
    "bazel_command",
]
