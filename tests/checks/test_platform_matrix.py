from __future__ import annotations

import json
import unittest
from types import MappingProxyType

from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
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
        # Profiles and plugins add languages, so only the stable ones are pinned.
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

    def test_jobs_that_never_run_python_are_not_python_s(self) -> None:
        """A job that runs nothing of Python (a docs build, a labeler) is no platform of Python, and is not listed
        under it (upstream #227)."""
        result = self._run(github_job("ubuntu-latest", "make docs"))
        self.assertNotIn(f"{GITHUB_WORKFLOW}: build: linux / no Python version", result.details)
        self.assertIn("0 OS(es) (none), 0 Python version(s) (none)", result.message)
        # A job that runs Python but pins no version is listed, with the runner's Python.
        result = self._run(github_job("ubuntu-latest", "python -m pytest"))
        self.assertIn(f"{GITHUB_WORKFLOW}: build: linux / default", result.details)

    def _workflow(self, **jobs: dict[str, object]) -> dict[str, str]:
        return {GITHUB_WORKFLOW: json.dumps({"jobs": jobs})}

    def test_jobs_of_another_kind_are_not_listed_beside_the_count(self) -> None:
        """A linux job sets up Python, a three-OS matrix job builds the docs: only the Python job is Python's, so the
        summary counts linux and lists nothing that contradicts it (upstream #227)."""
        setup = {"uses": "actions/setup-python@v5", "with": {"python-version": "${{ matrix.python }}"}}
        files = self._workflow(
            lint={
                "runs-on": "ubuntu-latest",
                "strategy": {"matrix": {"python": ["3.12", "3.13"]}},
                "steps": [setup, {"run": "python -m pytest"}],
            },
            docs={
                "runs-on": "${{ matrix.os }}",
                "strategy": {"matrix": {"os": ["ubuntu-latest", "macos-latest", "windows-latest"]}},
                "steps": [{"run": "make docs"}],
            },
        )
        result = self._run(files)
        self.assertIn("1 OS(es) (linux)", result.message)
        # The docs job runs no Python: it is not listed under it, so nothing contradicts the count.
        self.assertNotIn("set up no Python version", result.message)
        self.assertFalse([job for job in result.details if "docs" in job], result.details)

    def test_jobs_on_runners_of_unknown_os_are_counted_in_the_summary(self) -> None:
        """ghostty: most jobs run on a self-hosted runner whose name says no OS; the summary says how many, so a
        reader does not conclude the project never tests where those runners are (upstream #227)."""
        setup = {"uses": "actions/setup-python@v5", "with": {"python-version": "3.13"}}
        steps = [setup, {"run": "python -m pytest"}]
        files = self._workflow(
            a={"runs-on": "namespace-profile-sm", "steps": steps},
            b={"runs-on": "namespace-profile-lg", "steps": steps},
            c={"runs-on": "macos-latest", "steps": steps},
        )
        result = self._run(files)
        self.assertIn("1 OS(es) (macos)", result.message)
        self.assertIn("2 job(s) run on runners of unknown OS", result.message)

    def test_jobs_on_runners_of_unknown_os_without_a_toolchain_are_counted(self) -> None:
        """ghostty's C jobs on its namespace-profile runners name no compiler: the summary counts them too (#227)."""
        jobs = {
            name: {"runs-on": runner, "steps": [{"run": "cmake -B build && cmake --build build"}]}
            for name, runner in (("a", "namespace-profile-sm"), ("b", "namespace-profile-lg"), ("c", "ubuntu-latest"))
        }
        workflow = {GITHUB_WORKFLOW: json.dumps({"on": "push", "jobs": jobs})}
        with temp_project({**WELL_CONFIGURED, **workflow}) as root:
            result = platform_matrix.run(make_context(root))
        self.assertIn("2 job(s) run on runners of unknown OS", result.message)


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
    """A job naming no compiler counts as a C or C++ build on its runner's default compiler, unless it only runs
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
            # The job runs cmake, so it works with the CMake code too.
            self.assertEqual(job["ecosystems"], ["C++", "CMake", "Python"])


class PlatformQuestionTests(unittest.TestCase):
    def test_a_language_no_axis_covers_has_no_answer(self) -> None:
        from project_validator.facts import Facts
        from project_validator.questions.platforms import platform_answer

        self.assertIsNone(platform_answer("Klingon", Facts(())))
