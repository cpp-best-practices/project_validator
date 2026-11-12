"""Zig: built with `zig build` (`build.zig`, with `build.zig.zon` for the dependencies), judged by the Zig versions CI
runs, by the optimize modes it builds (Debug, and a release mode; ReleaseSafe keeps the safety checks) and by the tools
it runs: `zig build test`, kcov, `zig fmt` and lizard. Zig has no warnings (an unused variable is an error), so the
warning practices have no rule."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from project_validator.build_configurations import build_type_kinds
from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts import Command, Facts, Origin, Setting, resolved
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import SettingsReader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by
from project_validator.text import pattern
from project_validator.tools.limits import function_length_limiters

ZIG = frozenset({"Zig"})
BUILD_FILE = "build.zig"
# The optimize modes: Debug, and the release modes, of which only ReleaseSafe keeps the safety checks.
_OPTIMIZE_MODES = {"Debug": "debug", "ReleaseSafe": "release", "ReleaseFast": "release", "ReleaseSmall": "release"}
_BUILDS = (("zig", "build"), ("zig", "test"))


def _zig_builds(argv: tuple[str, ...]) -> bool:
    return starts_with(argv, *_BUILDS) is not None


def zig_build_types(command: Command) -> frozenset[str]:
    """The build type a `zig build` (or `zig test`) builds: its optimize mode (`-Doptimize=ReleaseSafe` to the build,
    `-O ReleaseSafe` to the compiler), Debug by default."""
    argv = resolved(command)
    if not _zig_builds(argv):
        return frozenset()
    modes = option_values(argv, "-Doptimize", "-O")
    return build_type_kinds(*(_OPTIMIZE_MODES.get(mode, mode) for mode in modes or ["Debug"]))


def _is_build_tree(directory: Path) -> bool:
    return directory.name in (".zig-cache", "zig-cache", "zig-out") and (directory.parent / BUILD_FILE).is_file()


ZIG_BUILD = BuildSystem(
    name="Zig build",
    files=(BUILD_FILE, "build.zig.zon"),
    languages=ZIG,
    is_build_tree=_is_build_tree,
    build_types=zig_build_types,
)


# --- Tests and coverage ---------------------------------------------------------------------------------------------

ZIG_TEST_FILES = TestFiles(
    name="test blocks in .zig files",
    languages=ZIG,
    path=re.compile(r"\.zig$"),
    contains=re.compile(r"^\s*test\s+(?:\"[^\"\n]*\"|\w+)?\s*\{", re.MULTILINE),
)


def _runs_tests(command: Command) -> bool:
    """`zig build test` (the `test` step) or `zig test <file>`."""
    argv = resolved(command)
    if starts_with(argv, ("zig", "test")) is not None:
        return True
    return starts_with(argv, ("zig", "build")) is not None and "test" in argv[2:]


ZIG_TEST = test_runner(
    name="zig build test",
    languages=ZIG,
    how="zig build test (or zig test src/main.zig)",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(ZIG_TEST_FILES.name),
)


def _kcov(command: Command) -> bool:
    """kcov counts the lines a test binary runs: `zig test --test-cmd kcov …`, or kcov run on the binary."""
    argv = resolved(command)
    return starts_with(argv, ("kcov",)) is not None or (
        "kcov" in option_values(argv, "--test-cmd") and _runs_tests(command)
    )


KCOV = coverage_tool(
    name="kcov",
    languages=ZIG,
    can={Granularity.LINE: "zig test src/main.zig --test-cmd kcov --test-cmd kcov-output --test-cmd-bin"},
    measures=lambda command, _facts: reported(Granularity.LINE) if _kcov(command) else None,
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# zig fmt has one style: `--check` fails on a file it would change, without it the file is rewritten.
ZIG_FMT = format_tool(
    name="zig fmt",
    languages=ZIG,
    can={Enforcement.CHECK: "zig fmt --check .", Enforcement.APPLY: "zig fmt ."},
    formats=flagged(("zig", "fmt"), checks=("--check",)),
    style=defined_by(),
)


# --- Hardening: release builds keep the safety checks -----------------------------------------------------------------

RELEASE_SAFE = pattern(
    "ReleaseSafe",
    r"-Doptimize=ReleaseSafe\b|(?<![\w-])-O\s*ReleaseSafe\b|\bpreferred_optimize_mode\s*=\s*\.ReleaseSafe\b"
    r"|\boptimize\s*=\s*\.ReleaseSafe\b",
)
ZIG_BUILD_SETTINGS = requirement_reader("Zig build settings", (BUILD_FILE,), (required(RELEASE_SAFE),))
PROGRAMS = "Zig programs"
_EXECUTABLE = re.compile(r"\baddExecutable\s*\(")


def _read_programs(path: str, text: str) -> Iterator[Setting]:
    """Whether the build defines an executable: a library has no binary to harden."""
    if _EXECUTABLE.search(text):
        yield Setting(origin=Origin(path=path), tool=PROGRAMS, key="executable", value=True)


ZIG_PROGRAMS = SettingsReader(name=PROGRAMS, files=(BUILD_FILE,), read=_read_programs)


def _no_program(facts: Facts) -> str | None:
    if facts.where(Setting, tool=PROGRAMS):
        return None
    return "no Zig executable is built (no addExecutable in build.zig); a library has no binary"


# Zig's safety checks (bounds, overflow, null and undefined behaviour) are on in Debug and ReleaseSafe; ReleaseFast
# and ReleaseSmall drop them. A release build that keeps them is the hardened one.
HARDENING = Practice(
    name=PracticeName.HARDENING,
    languages=ZIG,
    requirements=always(required(RELEASE_SAFE)),
    reads=(ZIG_BUILD_SETTINGS.name,),
    skipped=_no_program,
    words=Wording(
        kind="hardening options",
        searched="CI configuration and build.zig",
        hint="build the release with -Doptimize=ReleaseSafe (or make it the default: standardOptimizeOption(.{ "
        ".preferred_optimize_mode = .ReleaseSafe })), which keeps Zig's safety checks",
        failed="release builds drop Zig's safety checks: no ReleaseSafe build",
    ),
)

FUNCTION_LENGTH_LIMITERS = function_length_limiters(ZIG)


# --- Outputs --------------------------------------------------------------------------------------------------------

CACHE_DIRECTORY = BuildOutput(
    languages=ZIG,
    name="the Zig cache directory",
    globs=ignored_at_top_level(r"\.?zig-cache"),
    paths=directories(".zig-cache", "zig-cache"),
    hint="consider ignoring .zig-cache/ (and zig-cache/, its name before Zig 0.13)",
    artifacts=("/.zig-cache/", "/zig-cache/"),
)
OUT_DIRECTORY = BuildOutput(
    languages=ZIG,
    name="the zig-out directory",
    globs=ignored_at_top_level(r"zig-out"),
    paths=directories("zig-out"),
    hint="consider ignoring zig-out/",
    artifacts=("/zig-out/",),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# A version (`0.14.1`, a dev build `0.15.0-dev.351+64ef45eb0`) or `master`. The setup actions' input is `version`
# (mlugg/setup-zig, goto-bus-stop/setup-zig), which every action has: it counts after their own `uses:` line only;
# korandoru/setup-zig's is `zig-version`.
_ZIG_VERSION = r"(\d+\.\d+\.\d+(?:-dev\.\d+\+\w+)?|master|latest)"

ZIG_ECOSYSTEM = Ecosystem(
    label="Zig",
    languages=ZIG,
    build_systems=(ZIG_BUILD,),
    source_suffixes={".zig": "Zig"},
    # A `build.zig.zon` manifest is a file of the ecosystem with no language of its own.
    ambiguous_suffixes={".zon": None},
    toolchain=toolchain_patterns(
        "Zig",
        version=_ZIG_VERSION,
        inputs=("zig-version",),
        more=(
            rf"\buses: [\w-]+/setup-zig@[^\n]*\n(?:(?!uses:)[^\n]*\n)*?version:\s*[\"']?{_ZIG_VERSION}",
            rf"\"zig(?:-version)?\":\s*\"{_ZIG_VERSION}\"",
            rf"\bzigup\s+(?:fetch|run|default)\s+{_ZIG_VERSION}",
        ),
        programs=(*subcommands("zig", "build", "test", "fmt", "run", "cc", "c++", "translate-c"), "zigup"),
        setup=("zig",),
    ),
)

ZIG_VERSIONS = versions_axis("Zig version", "Zig", ZIG, compiled=True)
