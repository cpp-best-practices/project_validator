import json
import unittest
from collections.abc import Mapping

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY, PYTHON, RUST
from tests.support import (
    BARE_PROJECT,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_RUST,
    github_job,
    layouts_checked_as,
    run_as,
    run_in_every_layout,
)


def _workflow(matrix: Mapping[str, object], configure: str) -> dict[str, str]:
    job = {"runs-on": "${{ matrix.os }}", "strategy": {"matrix": matrix}, "steps": [{"run": configure}]}
    return {".github/workflows/ci.yml": json.dumps({"jobs": {"build": job}})}


class CiBuildTypesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, ci_build_types, files)

    # Only compiled languages have build types.
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(ci_build_types.languages, C_FAMILY | {"Rust"})

    def test_fails_without_ci(self) -> None:
        self.assertEqual(self._run(BARE_PROJECT).status, Status.FAIL)

    def test_fails_without_a_known_platform(self) -> None:
        result = self._run({".github/workflows/ci.yml": "jobs: {}\n"})
        self.assertEqual(result.message, "no OS/compiler combination found in CI configuration")

    def test_passes_with_debug_and_release_with_and_without_sanitizers_everywhere(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS, result.details)
        self.assertEqual(
            result.message,
            "all 5 OS/compiler combination(s) build Debug and Release, each with and without sanitizers",
        )

    def test_fails_when_build_type_is_never_specified(self) -> None:
        result = self._run(_workflow({"os": ["ubuntu-latest"]}, "cmake -S . -B build"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("1 of 1 OS/compiler combination(s)", result.message)
        self.assertIn("linux / gcc: no build type specified", result.details)

    def test_fails_when_only_one_kind_is_built(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "sanitize": ["ON", "OFF"]}
        result = self._run(
            _workflow(matrix, "cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_SANITIZERS=${{ matrix.sanitize }}")
        )
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("linux / gcc: missing Debug, Debug + sanitizers", result.details)

    def test_fails_when_sanitizers_are_never_enabled(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "build_type": ["Debug", "Release"]}
        result = self._run(_workflow(matrix, "cmake -DCMAKE_BUILD_TYPE=${{ matrix.build_type }}"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("linux / gcc: missing Debug + sanitizers, Release + sanitizers", result.details)

    def test_every_combination_needs_all_four_builds(self) -> None:
        matrix = {
            "os": ["ubuntu-latest"],
            "compiler": ["gcc", "clang"],
            "build_type": ["Debug", "Release"],
            "sanitize": ["ON", "OFF"],
            "exclude": [{"compiler": "clang", "sanitize": "ON"}],
        }
        configure = (
            "cmake -DCMAKE_CXX_COMPILER=${{ matrix.compiler }} -DCMAKE_BUILD_TYPE=${{ matrix.build_type }}"
            " -DENABLE_SANITIZERS=${{ matrix.sanitize }}"
        )
        result = self._run(_workflow(matrix, configure))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("1 of 2 OS/compiler combination(s)", result.message)
        self.assertEqual(result.details, ("linux / clang: missing Debug + sanitizers, Release + sanitizers",))

    def test_cmake_template_maintainer_mode_toggles_sanitizers(self) -> None:
        matrix = {"os": ["ubuntu-latest"], "build_type": ["Release", "Debug"], "maintainer": ["ON", "OFF"]}
        configure = (
            "cmake -DCMAKE_BUILD_TYPE:STRING=${{matrix.build_type}}"
            " -D${{ env.PROJECT_NAME }}_PACKAGING_MAINTAINER_MODE:BOOL=${{matrix.maintainer}}"
        )
        self.assertEqual(self._run(_workflow(matrix, configure)).status, Status.PASS)


class RustCiBuildTypesTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, ci_build_types, files, RUST)

    def test_passes_with_debug_and_release_with_and_without_sanitizers_everywhere(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_RUST))
        self.assertEqual(
            result,
            Result.passed(
                "all 6 OS/Rust toolchain combination(s) build Debug and Release, each with and without sanitizers"
            ),
        )

    def test_fails_without_a_known_platform(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "jobs: {}\n"})
        self.assertEqual(result.message, "no OS/Rust toolchain combination found in CI configuration")

    def test_fails_when_only_release_is_built_without_sanitizers(self) -> None:
        release_only = "cargo +stable build --release && cargo +stable test --release"
        result = self._run(github_job("ubuntu-latest", release_only))
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.details, ("linux / stable: missing Debug, Debug + sanitizers, Release + sanitizers",))

    def test_fails_when_no_cargo_command_builds(self) -> None:
        result = self._run(github_job("ubuntu-latest", "cargo clippy", "cargo test --profile ci"))
        self.assertEqual(result.details, ("linux / default: no build type specified",))

    def test_python_is_not_judged(self) -> None:
        self.assertEqual(layouts_checked_as(ci_build_types, PYTHON), ())
