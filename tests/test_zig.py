"""The Zig profile's rules, judged by the generic checks in the Zig build and Zig sources layouts."""

from __future__ import annotations

import unittest
from pathlib import Path

from project_validator.build_configurations import sanitizers_enabled
from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.coverage import coverage
from project_validator.checks.function_limits import function_limits
from project_validator.checks.hardening import hardening
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.zig import ZIG_ECOSYSTEM, zig_build_types
from tests.support import (
    GITHUB_WORKFLOW,
    command,
    github_job,
    github_steps,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
)

ZIG = frozenset({"Zig"})
TESTS = {"src/shop.zig": 'const std = @import("std");\n\ntest "total" {\n    try std.testing.expect(true);\n}\n'}
EXECUTABLE = (
    'pub fn build(b: *std.Build) void {\n    const exe = b.addExecutable(.{ .name = "shop" });\n'
    "    b.installArtifact(exe);\n}\n"
)
PREFERRED = (
    "const optimize = b.standardOptimizeOption(.{ .preferred_optimize_mode = .ReleaseSafe });\n    _ = optimize;\n"
    "    b.installArtifact(exe);"
)
LIBRARY = 'pub fn build(b: *std.Build) void {\n    _ = b.addModule("shop", .{});\n}\n'
ZIG_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            zig: ["0.13.0", "0.14.1"]
            optimize: [Debug, ReleaseSafe]
            sanitize: ["", "-fsanitize-c"]
        steps:
          - uses: mlugg/setup-zig@v2
            with:
              version: ${{ matrix.zig }}
          - run: zig build -Doptimize=${{ matrix.optimize }}
          - run: zig test src/shop.zig -O ${{ matrix.optimize }} ${{ matrix.sanitize }}
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_sources_and_the_build_files(self) -> None:
        with temp_project({"src/main.zig": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (ZIG, frozenset()))
        with temp_project({"build.zig": "", "build.zig.zon": ".{}", "src/main.zig": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.build_systems, frozenset({"Zig build"}))
        self.assertEqual(structure.unrecognised_suffixes, ())

    def test_build_trees(self) -> None:
        with temp_project({"build.zig": "", ".zig-cache/h/x": "", "zig-cache/x": "", "zig-out/bin/shop": ""}) as root:
            for name in (".zig-cache", "zig-cache", "zig-out"):
                self.assertTrue(is_build_tree(Path(root, name)), name)
            self.assertFalse(is_build_tree(Path(root, "src")))

    def test_optimize_modes_are_build_types(self) -> None:
        self.assertEqual(zig_build_types(command("zig build test")), frozenset({"debug"}))
        self.assertEqual(zig_build_types(command("zig build -Doptimize=ReleaseFast")), frozenset({"release"}))
        self.assertEqual(zig_build_types(command("zig test src/main.zig -O ReleaseSafe")), frozenset({"release"}))
        self.assertEqual(zig_build_types(command("zig test src/main.zig -OReleaseSmall")), frozenset({"release"}))
        self.assertEqual(zig_build_types(command("zig fmt --check .")), frozenset())

    def test_zigs_sanitizer_flags_count(self) -> None:
        self.assertTrue(sanitizers_enabled(("zig test src/main.zig -fsanitize-thread",)))
        self.assertTrue(sanitizers_enabled(("zig test src/main.zig -fsanitize-c",)))
        self.assertFalse(sanitizers_enabled(("zig test src/main.zig",)))

    def test_ci_usage(self) -> None:
        for text in ("zig build test", "zig fmt --check .", "uses: mlugg/setup-zig@v2", "zigup 0.14.1"):
            with self.subTest(text=text):
                self.assertTrue(ZIG_ECOSYSTEM.used_by(text))
        self.assertFalse(ZIG_ECOSYSTEM.used_by("npm test"))


class ZigTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, ZIG_ECOSYSTEM)

    def test_zig_build_test_runs_the_test_blocks(self) -> None:
        for line in ("zig build test", "zig build test --summary all", "zig test src/shop.zig"):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TESTS, **_ci("zig build")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("zig build test")).status, Status.FAIL)

    def test_kcov_counts_lines(self) -> None:
        passed = Result.passed("line coverage is reported with kcov")
        self.assertEqual(
            self._run(coverage, _ci("zig test src/shop.zig --test-cmd kcov --test-cmd out --test-cmd-bin")), passed
        )
        self.assertEqual(
            self._run(coverage, _ci("zig build test", "kcov --include-pattern=src out zig-out/bin/test")), passed
        )
        self.assertEqual(self._run(coverage, _ci("zig build test")).status, Status.FAIL)

    def test_zig_fmt(self) -> None:
        self.assertEqual(
            self._run(code_formatting, _ci("zig fmt --check .")), Result.passed("CI enforces the zig fmt style")
        )
        self.assertEqual(self._run(code_formatting, _ci("zig fmt .")).status, Status.FAIL)

    def test_a_release_safe_build_is_the_hardened_one(self) -> None:
        layout = "Zig build"
        passed = Result.passed("hardening options are enabled: ReleaseSafe")
        for line in ("zig build -Doptimize=ReleaseSafe", "zig test src/shop.zig -O ReleaseSafe"):
            with self.subTest(line=line):
                self.assertEqual(run_in_layout(self, layout, hardening, _ci(line)), passed)
        preferred = {"build.zig": EXECUTABLE.replace("b.installArtifact(exe);", PREFERRED)}
        self.assertEqual(run_in_layout(self, layout, hardening, preferred), passed)
        self.assertEqual(
            run_in_layout(self, layout, hardening, _ci("zig build -Doptimize=ReleaseFast")).status, Status.FAIL
        )
        self.assertEqual(run_in_layout(self, layout, hardening, {"build.zig": LIBRARY}).status, Status.SKIP)
        self.assertEqual(run_in_layout(self, "Zig sources", hardening, _ci("zig build")).status, Status.SKIP)

    def test_ci_builds_debug_and_a_release_mode_with_and_without_sanitizers(self) -> None:
        self.assertEqual(self._run(ci_build_types, {GITHUB_WORKFLOW: ZIG_MATRIX}).status, Status.PASS)
        self.assertEqual(self._run(ci_build_types, _ci("zig build test")).status, Status.FAIL)

    def test_lizard_limits_zig_functions(self) -> None:
        self.assertEqual(self._run(function_limits, _ci("lizard --length 30 --warnings_only src")).status, Status.PASS)

    def test_the_cache_and_out_directories_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": ".zig-cache/\nzig-out/\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "zig-cache/\n/zig-out\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "zig-out/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_zig_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: ZIG_MATRIX})
        self.assertIn("2 Zig version(s) (0.13.0, 0.14.1)", result.message)
        for files, version in (
            (github_steps("uses: korandoru/setup-zig@v1", "run: zig build test"), "default"),
            (_ci("zigup fetch 0.15.0-dev.351+64ef45eb0", "zig build test"), "0.15.0-dev.351+64ef45eb0"),
            (_ci("zig build test"), "default"),
        ):
            with self.subTest(files=files):
                self.assertIn(f"1 Zig version(s) ({version})", self._run(platform_matrix, files).message)
        # Another action's `version` input names no Zig version.
        other = github_steps("uses: fortran-lang/setup-fortran@v1", "run: zig build test")
        other[GITHUB_WORKFLOW] = other[GITHUB_WORKFLOW].replace(
            '"uses": "fortran-lang/setup-fortran@v1"',
            '"uses": "fortran-lang/setup-fortran@v1", "with": {"version": "14"}',
        )
        self.assertIn("1 Zig version(s) (default)", self._run(platform_matrix, other).message)
