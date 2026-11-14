"""The sanitizers check: C/C++ builds with AddressSanitizer and UndefinedBehaviorSanitizer in some configuration (one
warns, neither fails); Rust runs Miri or builds with -Zsanitizer; Go runs the race detector."""

from __future__ import annotations

import unittest

from project_validator.checks.sanitizers import sanitizers
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.rust import RUST
from tests.support import (
    BARE_PROJECT,
    WELL_CONFIGURED,
    WELL_CONFIGURED_GO,
    WELL_CONFIGURED_RUST,
    c_family_layouts_built_with,
    github_job,
    layout_project,
    make_context,
    run_as,
    run_in_layout,
)

BOTH = Result.passed("sanitizers are enabled: AddressSanitizer, UndefinedBehaviorSanitizer")
HINT = (
    "build with -fsanitize=address,undefined (MSVC: /fsanitize=address) in at least one configuration, behind an "
    "option CI turns on (Meson: -Db_sanitize=address,undefined)"
)
NONE = Result.failed("no sanitizers found; enable AddressSanitizer, UndefinedBehaviorSanitizer", HINT)
PROJECT = "project(p LANGUAGES CXX)\n"


def _cmake(test: unittest.TestCase, build: str, ci: dict[str, str] | None = None) -> Result:
    return run_in_layout(test, "CMake C++", sanitizers, {"CMakeLists.txt": PROJECT + build, **(ci or {})})


class SanitizersTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(sanitizers.languages, C_FAMILY | {"Rust", "Go"})


class CAndCxxSanitizersTests(unittest.TestCase):
    def test_the_well_configured_project_passes_and_the_bare_one_fails(self) -> None:
        for layout in c_family_layouts_built_with(sanitizers, "CMake"):
            with layout_project(self, layout, WELL_CONFIGURED) as root:
                self.assertEqual(sanitizers.run(make_context(root)).status, Status.PASS)
        self.assertEqual(run_in_layout(self, "CMake C++", sanitizers, BARE_PROJECT), NONE)

    def test_both_sanitizers_pass_in_one_option_or_two(self) -> None:
        for build in (
            "add_compile_options(-fsanitize=address,undefined)\n",
            "add_compile_options(-fsanitize=undefined -fsanitize=address)\n",
            "target_compile_options(app PRIVATE -fsanitize=address,undefined,leak)\n",
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fsanitize=address,undefined")\n',
            "target_link_libraries(app PRIVATE -fsanitize=address,undefined)\n",
        ):
            with self.subTest(build=build):
                self.assertEqual(_cmake(self, build), BOTH)

    def test_behind_an_option_counts_whatever_ci_sets_it_to(self) -> None:
        build = (
            'option(ENABLE_SANITIZERS "" OFF)\nif(ENABLE_SANITIZERS)\n'
            "  add_compile_options(-fsanitize=address,undefined)\nendif()\n"
        )
        self.assertEqual(_cmake(self, build), BOTH)

    def test_one_sanitizer_warns_naming_the_other(self) -> None:
        self.assertEqual(
            _cmake(self, "add_compile_options(-fsanitize=address)\n"),
            Result.warned("missing sanitizers: UndefinedBehaviorSanitizer", "found AddressSanitizer"),
        )
        self.assertEqual(
            _cmake(self, "add_compile_options(/fsanitize=address)\n"),
            Result.warned("missing sanitizers: UndefinedBehaviorSanitizer", "found AddressSanitizer"),
        )
        self.assertEqual(
            _cmake(self, "add_compile_options(-fsanitize=undefined,thread)\n"),
            Result.warned("missing sanitizers: AddressSanitizer", "found UndefinedBehaviorSanitizer"),
        )

    def test_other_sanitizers_and_the_fuzzer_alone_are_not_asked_for(self) -> None:
        self.assertEqual(_cmake(self, "add_compile_options(-fsanitize=thread)\n").status, Status.FAIL)
        self.assertEqual(_cmake(self, "add_compile_options(-fsanitize=fuzzer)\n").status, Status.FAIL)
        self.assertEqual(_cmake(self, "add_compile_options(-fsanitize-address-use-after-scope)\n").status, Status.FAIL)

    def test_cmake_template_options_count_on_by_default_or_set_by_ci(self) -> None:
        defaults = 'option(ENABLE_SANITIZER_ADDRESS "" ON)\noption(ENABLE_SANITIZER_UNDEFINED_BEHAVIOR "" ON)\n'
        self.assertEqual(_cmake(self, defaults), BOTH)
        off = 'option(myproject_ENABLE_SANITIZER_ADDRESS "" OFF)\noption(myproject_ENABLE_SANITIZER_UNDEFINED "" OFF)\n'
        ci = github_job(
            "ubuntu-latest",
            "cmake -S . -B build -Dmyproject_ENABLE_SANITIZER_ADDRESS=ON "
            "-Dmyproject_ENABLE_SANITIZER_UNDEFINED:BOOL=TRUE",
        )
        self.assertEqual(_cmake(self, off, ci), BOTH)
        self.assertEqual(_cmake(self, off).status, Status.FAIL)

    def test_flags_on_the_ci_command_line_count(self) -> None:
        ci = github_job("ubuntu-latest", 'cmake -S . -B build -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined"')
        self.assertEqual(_cmake(self, "", ci), BOTH)
        ci = github_job("ubuntu-latest", "cmake -S . -B build", "cmake --build build")
        self.assertEqual(_cmake(self, "", ci), NONE)

    def test_meson_b_sanitize_in_the_build_or_on_the_command_line(self) -> None:
        def meson(default_options: str, ci: dict[str, str] | None = None) -> Result:
            build = f"project('app', 'cpp'{default_options})\n"
            return run_in_layout(self, "Meson C++", sanitizers, {"meson.build": build, **(ci or {})})

        self.assertEqual(meson(", default_options: ['b_sanitize=address,undefined']"), BOTH)
        self.assertEqual(meson("", github_job("ubuntu-latest", "meson setup b -Db_sanitize=address,undefined")), BOTH)
        self.assertEqual(
            meson(", default_options: ['b_sanitize=address']"),
            Result.warned("missing sanitizers: UndefinedBehaviorSanitizer", "found AddressSanitizer"),
        )
        self.assertEqual(meson("").status, Status.FAIL)


class RustSanitizersTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, sanitizers, files, RUST)

    def test_miri_or_a_nightly_sanitizer_passes_and_nothing_fails(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_RUST)).status, Status.PASS)
        for line, found in (
            ("cargo +nightly miri test", "cargo miri test"),
            ("cargo miri nextest run", "cargo miri test"),
            ("RUSTFLAGS=-Zsanitizer=address cargo +nightly test --target x86_64-unknown-linux-gnu", "-Zsanitizer"),
        ):
            with self.subTest(line=line):
                result = self._run(github_job("ubuntu-latest", line))
                self.assertEqual(result, Result.passed(f"sanitizers run in CI: {found}"))
        result = self._run(github_job("ubuntu-latest", "cargo test"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message, "no sanitizer runs in CI; run cargo +nightly miri test or build with -Zsanitizer=address"
        )


class GoSanitizersTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, sanitizers, files, GO)

    def test_the_race_detector_passes_and_nothing_fails(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_GO)).status, Status.PASS)
        for line in ("go test -race ./...", "gotestsum -- -race ./...", "go test -v -race -count=1 ./..."):
            with self.subTest(line=line):
                result = self._run(github_job("ubuntu-latest", line))
                self.assertEqual(result, Result.passed("sanitizers run in CI: go test -race"))
        result = self._run(github_job("ubuntu-latest", "go test -asan ./..."))
        self.assertEqual(result, Result.passed("sanitizers run in CI: go test -asan"))
        result = self._run(github_job("ubuntu-latest", "go test ./..."))
        self.assertEqual(
            result,
            Result.failed("no sanitizer runs in CI; run go test -race", "run go test -race (the race detector) in CI"),
        )
