"""The test aspect of tools (see `project_validator.facts.tools`): a test runner's run runs the project's tests.

What makes a file a test file is a language's own (`*_test.go` with `Test` functions, `@Test` methods under
`src/test/java`): a `TestFiles` component says so, and each file it matches is a `TestFile` fact. A runner's
`Definition` is where the tests it runs are defined: the test files of the kinds it runs, or the registrations a build
system reads (CTest's `add_test`, Meson's `test()`). Runners are ordinary `Tool`s; `test_runner` and `tested` only spell
them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from project_validator.components import known
from project_validator.core import Project
from project_validator.facts import Fact, Facts, Setting
from project_validator.facts.roles import role
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

TEST = "test"
RUNS = "runs"


@dataclass(frozen=True, slots=True, kw_only=True)
class TestFiles:
    """A kind of test file of `languages`: a source whose path matches `path` and, if given, whose text `contains` a
    test. `name` says what it is (`Test functions in *_test.go files`)."""

    name: str
    languages: frozenset[str]
    path: re.Pattern[str]
    contains: re.Pattern[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TestFile(Fact):
    """A source file with tests in it, of the kind `kind` (a `TestFiles` name)."""

    language: str
    kind: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Probe:
    """An extraction that runs the project's own tools, only when asked to (`--build`): `run` returns facts."""

    name: str
    run: Callable[[Project, object], Iterable[Fact]]


def known_test_files() -> tuple[TestFiles, ...]:
    return known(TestFiles)


def known_probes() -> tuple[Probe, ...]:
    return known(Probe)


def test_file_facts(project: Project, facts: Facts, kinds: Iterable[TestFiles]) -> Iterator[TestFile]:
    """The source files (outside vendored code) that each kind of test file matches."""
    from project_validator.facts.structure import SourceFile  # structure reads the profiles, which define test files

    kinds = tuple(kinds)
    for source in facts.of(SourceFile):
        if source.language is None or role(source.path) == "vendored":
            continue
        for kind in kinds:
            if source.language not in kind.languages or not kind.path.search(source.path):
                continue
            if kind.contains is None or kind.contains.search(project.read_text(source.path)):
                yield TestFile(origin=source.origin, language=source.language, kind=kind.name)


def tests_of(*kinds: str) -> Definition:
    """Tests defined by the test files of `kinds`; a runner has no tests without them. A separate test project's
    tests count for every unit."""
    names = frozenset(kinds)

    def found(facts: Facts) -> Iterator[str]:
        return (test.origin.path for test in facts.of(TestFile) if test.kind in names)

    return Definition(found=found, default=False, describe=" or ".join(kinds), from_test_units=True)


def test_runner(
    *, name: str, languages: frozenset[str], how: str, runs: Claim, tests: Definition, reads: tuple[str, ...] = ()
) -> Tool:
    """A test runner: `how` to run it, and `tests`, where the tests it runs are defined."""
    return Tool(
        name=name, languages=languages, can={TEST: {RUNS: how}}, claims=runs, reads=reads, definitions={TEST: tests}
    )


def tested(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(TEST, RUNS, read=read, heuristic=heuristic)


__all__ = [
    "RUNS",
    "TEST",
    "Probe",
    "TestFile",
    "TestFiles",
    "known_probes",
    "known_test_files",
    "test_file_facts",
    "test_runner",
    "tested",
    "tests_of",
]
