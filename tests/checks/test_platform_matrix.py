import json
import unittest
from types import MappingProxyType

from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY, PYTHON, RUST
from tests.support import (
    BARE_PROJECT,
    GITHUB_WORKFLOW,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    github_job,
    make_context,
    run_as,
    run_in_every_layout,
    temp_project,
)


class PlatformMatrixTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        # Plugins (and later built-in profiles) add languages; the README matrix pins the exact list.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, platform_matrix.languages)

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


MIXED_PROJECT = MappingProxyType(
    {"CMakeLists.txt": "", "src/main.cpp": "", "pyproject.toml": "", "app/__init__.py": ""}
)


class JobAttributionTests(unittest.TestCase):
    """A job naming no compiler counts as a C/C++ build on its runner's default compiler, unless it only runs
    another ecosystem's tools."""

    def _jobs(self, *jobs: tuple[str, str]) -> dict[str, str]:
        return {
            GITHUB_WORKFLOW: json.dumps(
                {
                    "jobs": {
                        f"j{index}": {"runs-on": runs_on, "steps": [{"run": step}]}
                        for index, (runs_on, step) in enumerate(jobs)
                    }
                }
            )
        }

    def _c_and_cxx_result(self, *jobs: tuple[str, str]) -> str:
        with temp_project({**MIXED_PROJECT, **self._jobs(*jobs)}) as root:
            return platform_matrix.run(make_context(root)).message.split("; Python: ")[0]

    def test_a_python_only_job_is_not_a_c_and_cxx_build(self) -> None:
        message = self._c_and_cxx_result(
            ("windows-latest", "cmake --build build"), ("macos-latest", "python -m pytest")
        )
        self.assertIn("1 OS(es) (windows), 1 compiler(s) (msvc)", message)

    def test_a_job_that_builds_with_cmake_and_python_tools_is_a_c_and_cxx_build(self) -> None:
        message = self._c_and_cxx_result(("ubuntu-latest", "pip install gcovr && cmake --build build && gcovr"))
        self.assertIn("1 compiler(s) (gcc)", message)

    def test_a_job_that_names_a_compiler_is_a_c_and_cxx_build(self) -> None:
        message = self._c_and_cxx_result(("ubuntu-latest", "CXX=clang++ python build.py"))
        self.assertIn("1 compiler(s) (clang)", message)

    def test_a_job_of_no_recognisable_ecosystem_is_a_c_and_cxx_build(self) -> None:
        message = self._c_and_cxx_result(("ubuntu-latest", "./build.sh"))
        self.assertIn("1 compiler(s) (gcc)", message)

    def test_the_project_map_lists_each_jobs_ecosystems(self) -> None:
        with temp_project(
            {**MIXED_PROJECT, **self._jobs(("ubuntu-latest", "pip install gcovr && cmake -B b"))}
        ) as root:
            [job] = make_context(root).structure.as_dict()["ci"]["jobs"]  # type: ignore[index]
            self.assertEqual(job["ecosystems"], ["C/C++", "Python"])
