"""Bazel as a build system (upstream #207): a project with a `MODULE.bazel`, `WORKSPACE` or `BUILD.bazel` file builds
with Bazel. Its BUILD files (`BUILD`, `BUILD.bazel`) are read for the rules they call (`syntax`): the kinds of rule each
uses, and the test rules (`cc_test`, `swift_test`, `sh_test`, any `*_test`) it defines, which `bazel test` (or
`bazel coverage`) runs. A test rule tests the language of the sources it lists or, when they say none, the language
its kind tests (`cc_test` C and C++); a macro whose sources are not written out tests a language not known.

A command's `--compilation_mode` (`-c`) is its build type: `dbg` is Debug, `opt` Release, and the default,
`fastbuild`, neither. Bazel's output directories (`bazel-bin`, `bazel-out`, `bazel-<workspace>`) are build trees.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from project_validator.build_systems.bazel.syntax import Rule, rules
from project_validator.build_systems.model import BuildSystem
from project_validator.facts import Command, Fact, Facts, Origin, Setting, Unknown, resolved
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


# The languages Bazel's own and common rules test; the test rule of another kind (a macro, `api_cc_test`) tests the
# language of the sources it lists.
_KIND_LANGUAGES: dict[str, frozenset[str]] = {
    "cc_test": frozenset({"C", "C++"}),
    "swift_test": frozenset({"Swift"}),
    "py_test": frozenset({"Python"}),
    "sh_test": frozenset({"Shell"}),
    "go_test": frozenset({"Go"}),
    "java_test": frozenset({"Java"}),
    "rust_test": frozenset({"Rust"}),
    "kt_jvm_test": frozenset({"Kotlin"}),
}


def _sources(build_file: str, rule: Rule) -> tuple[str, ...]:
    """The files a rule's `srcs` lists, from the top of the workspace; not its labels (`:gen`, `//lib:a`), nor
    sources it computes (`glob()`)."""
    listed = rule.attributes.get("srcs")
    if not isinstance(listed, list):
        return ()
    directory = posixpath.dirname(build_file)
    return tuple(
        posixpath.normpath(posixpath.join(directory, source))
        for source in listed
        if isinstance(source, str) and not source.startswith((":", "//", "@"))
    )


def _test_rule(path: str, rule: Rule, name: str) -> Iterator[Fact]:
    """A test rule, as its kind and the sources it lists; unknown when neither tells the language it tests."""
    sources = _sources(path, rule)
    origin = Origin(path=path, at=(name,))
    yield Setting(origin=Origin(path=path), tool=BAZEL_NAME, key=f"test.{name}", value=(rule.kind, *sources))
    if not sources and rule.kind not in _KIND_LANGUAGES:
        reason = f"its kind, {rule.kind}, and its sources do not say which language it tests"
        yield Unknown(
            origin=origin, subject=f"the Bazel test rule {name}", reason=reason, hides="settings", tools=(BAZEL_NAME,)
        )


def _read_build_file(path: str, text: str) -> Iterator[Fact]:
    """The kinds of rule a BUILD file calls, and its test rules."""
    found, problems = rules(text)
    if problems and not found:
        first = problems[0]
        yield unreadable(BAZEL_NAME, path, ParseError(first.reason, first.span.line if first.span else None))
        return
    kinds = tuple(sorted({rule.kind for rule in found if rule.kind != "load"}))
    if kinds:
        yield Setting(origin=Origin(path=path), tool=BAZEL_NAME, key="rules", value=kinds)
    for rule in found:
        if rule.kind.endswith("_test") and rule.name is not None:
            yield from _test_rule(path, rule, rule.name)


BAZEL_BUILD_FILES = SettingsReader(name=BAZEL_NAME, files=("BUILD", "BUILD.bazel"), read=_read_build_file)


def _tests_of(language: str) -> Callable[[Facts], Iterator[str]]:
    """The BUILD files that define a test rule of `language`: one whose sources are of it, or, when the sources it
    lists say no language, whose kind tests it."""

    def found(facts: Facts) -> Iterator[str]:
        from project_validator.facts.structure import SourceFile  # structure reads the profiles, which define runners

        languages = {source.path: source.language for source in facts.of(SourceFile) if source.language}
        for setting in facts.where(Setting, tool=BAZEL_NAME):
            if not setting.key.startswith("test."):
                continue
            kind, *sources = cast(tuple[str, ...], setting.value)
            tested_languages = frozenset(languages[source] for source in sources if source in languages)
            if language in (tested_languages or _KIND_LANGUAGES.get(kind, frozenset())):
                yield setting.path

    return found


def _bazel_test(command: Command, _facts: Facts) -> Run | None:
    found = bazel_command(resolved(command))
    return tested() if found is not None and found[0] in _TESTING else None


# `bazel test` of each language a Bazel project builds: it runs the test rules of that language.
BAZEL_TEST = tuple(
    test_runner(
        name="bazel test",
        languages=frozenset({language}),
        how="bazel test",
        runs=_bazel_test,
        tests=Definition(
            found=_tests_of(language),
            default=False,
            describe="tests defined by Bazel test rules (cc_test, swift_test, sh_test, …) in BUILD files",
        ),
        reads=(BAZEL_NAME,),
    )
    for language in ("C", "C++", "Objective-C", "Objective-C++", "Swift")
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
