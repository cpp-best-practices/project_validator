import unittest

from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Result, Status
from project_validator.ecosystems import PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    GITHUB_WORKFLOW,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    github_job,
    run_as,
    run_in_every_layout,
)


class PlatformMatrixTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(platform_matrix.languages, C_FAMILY | {"Python", "Rust"})

    def test_fails_without_ci(self) -> None:
        self.assertEqual(run_in_every_layout(self, platform_matrix, BARE_PROJECT).status, Status.FAIL)

    def test_passes_with_an_expanded_matrix(self) -> None:
        result = run_in_every_layout(self, platform_matrix, WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS)
        self.assertIn(
            "3 OS(es) (linux, macos, windows), 3 compiler(s) (clang, gcc, msvc), 5 combination(s)", result.message
        )

    def test_fails_with_a_single_platform_and_explains_why(self) -> None:
        files = {".github/workflows/ci.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: []\n"}
        result = run_in_every_layout(self, platform_matrix, files)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 operating systems (found 1)", result.message)
        self.assertIn(".github/workflows/ci.yml: a: linux / gcc (runner default)", result.details)

    def test_unstructured_providers_are_scanned_heuristically(self) -> None:
        for provider, path in UNSTRUCTURED_CI_FILES.items():
            with self.subTest(ci=provider):
                result = run_in_every_layout(self, platform_matrix, {path: "os: linux\ncompiler: gcc\n"})
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn(f"{path}: {provider} is scanned heuristically", result.details)
                self.assertIn(f"{path}: linux / gcc", result.details)


class PythonPlatformMatrixTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, platform_matrix, files, PYTHON)

    def test_passes_with_several_operating_systems_and_python_versions(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_PYTHON))
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(
            result.message,
            "CI covers 3 OS(es) (linux, macos, windows), 2 Python version(s) (3.13, 3.14), 6 combination(s)",
        )

    def test_fails_with_a_single_python_version_and_explains_why(self) -> None:
        matrix = {"os": ["ubuntu-latest", "windows-latest"]}
        result = self._run(github_job("${{ matrix.os }}", "python -m pytest", matrix=matrix))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 Python versions (found 1)", result.message)
        self.assertIn("at least 3 OS/Python version combinations (found 2)", result.message)
        self.assertIn(f"{GITHUB_WORKFLOW}: build (ubuntu-latest): linux / default", result.details)

    def test_python_versions_are_read_from_gitlab_images(self) -> None:
        pipeline = "".join(
            f"test-{version}:\n  image: python:{version}\n  script: [pytest]\n" for version in ("3.12", "3.13")
        )
        result = self._run({".gitlab-ci.yml": pipeline})
        self.assertIn("2 Python version(s) (3.12, 3.13)", result.message)
        self.assertIn("at least 2 operating systems (found 1)", result.message)

    def test_jobs_that_never_run_python_are_not_counted(self) -> None:
        result = self._run(github_job("ubuntu-latest", "make docs"))
        self.assertIn(f"{GITHUB_WORKFLOW}: build: linux / no Python version", result.details)
        self.assertIn("0 Python version(s) (none)", result.message)


class RustPlatformMatrixTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, platform_matrix, files, RUST)

    def test_passes_with_several_operating_systems_and_toolchains(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_RUST))
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("2 Rust toolchain(s) (nightly, stable), 6 combination(s)", result.message)

    def test_unstructured_providers_are_scanned_for_toolchains(self) -> None:
        for provider, path in UNSTRUCTURED_CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "os: [linux, osx]\nscript:\n  - cargo +1.80 test\n  - cargo +nightly test\n"})
                self.assertEqual(result.status, Status.PASS)
                self.assertIn("2 Rust toolchain(s) (1.80, nightly), 4 combination(s)", result.message)

    def test_fails_with_the_runner_default_toolchain_only(self) -> None:
        result = self._run(github_job("ubuntu-latest", "cargo test"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("at least 2 Rust toolchains (found 1)", result.message)
        self.assertIn(f"{GITHUB_WORKFLOW}: build: linux / default", result.details)
