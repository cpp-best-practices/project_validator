"""Gleam: packages described by `gleam.toml` (`.gleam` sources, compiled to Erlang or JavaScript), judged by what CI
runs: `gleam test` over the test modules (`tests-run`) and `gleam format --check` (`code-formatting`); `gleam build`
writes its output to `build/`, which is ignored and never committed (upstream #264)."""

from __future__ import annotations

import re
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

GLEAM = "Gleam"
GLEAM_ONLY = frozenset({GLEAM})


def _is_build_directory(directory: Path) -> bool:
    """`build/` beside a `gleam.toml`, where gleam writes the compiled packages."""
    return directory.name == "build" and (directory.parent / "gleam.toml").is_file()


GLEAM_BUILD = BuildSystem(name="gleam", files=("gleam.toml",), languages=GLEAM_ONLY, is_build_tree=_is_build_directory)

GLEAM_ECOSYSTEM = Ecosystem(
    label="Gleam",
    links={"Gleam": "https://gleam.run/"},
    languages=GLEAM_ONLY,
    build_systems=(GLEAM_BUILD,),
    source_suffixes={".gleam": GLEAM},
    # erlef/setup-beam's `gleam-version`.
    toolchain=toolchain_patterns(
        GLEAM,
        inputs=("gleam-version",),
        programs=subcommands("gleam", "test", "format", "build", "run", "check", "deps", "export"),
    ),
)

# gleeunit's (or startest's) test modules under test/, whose `pub fn …_test()` functions are the tests.
GLEAM_TESTS = TestFiles(
    name="test modules under test/ (gleeunit)",
    languages=GLEAM_ONLY,
    path=re.compile(r"(?:^|/)test/.+\.gleam$"),
    contains=re.compile(r"\bgleeunit\b|\bstartest\b|^pub fn \w+_test\s*\(", re.MULTILINE),
)
GLEAM_TEST = test_runner(
    name="gleam test",
    languages=GLEAM_ONLY,
    how="gleam test",
    runs=when(starts(("gleam", "test")), tested),
    tests=tests_of(GLEAM_TESTS.name),
)
# Gleam has one style, its formatter's.
GLEAM_FORMAT = format_tool(
    name="gleam format",
    languages=GLEAM_ONLY,
    can={Enforcement.CHECK: "gleam format --check src test", Enforcement.APPLY: "gleam format src test"},
    formats=flagged(("gleam", "format"), checks=("--check",)),
    style=defined_by(),
)
GLEAM_BUILD_OUTPUT = BuildOutput(
    languages=GLEAM_ONLY,
    name="the build directory",
    globs=ignored_at_top_level(r"build"),
    paths=directories("build"),
    hint="consider ignoring build/ (gleam writes the compiled packages there)",
    artifacts=("build/",),
)
