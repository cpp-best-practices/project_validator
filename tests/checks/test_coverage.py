from __future__ import annotations

import unittest

from project_validator.checks.coverage import coverage
from project_validator.core import Options, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import (
    CI_FILES,
    GITHUB_WORKFLOW,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    ci_running,
    github_job,
    run_as,
    run_in_every_layout,
)

ALLOW_UNKNOWN = Options(allow_unknown=True)
C_PATH_HINT = (
    "consider adding path coverage (e.g. lcov --mcdc-coverage, gcov --conditions, llvm-cov show -show-mcdc, "
    "gcc -fcondition-coverage, gcc -fpath-coverage, clang -fcoverage-mcdc)"
)


class CoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_in_every_layout(self, coverage, files, options=options)

    def test_declares_the_languages_it_judges(self) -> None:
        # Coverage tools add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, coverage.languages)

    def test_fails_without_branch_coverage_and_says_what_is_reported(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "gcovr --txt-metric line"), ALLOW_UNKNOWN)
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn("line coverage is reported with gcovr", result.details)

    def test_what_ci_configuration_that_is_not_parsed_hides_is_an_error_unless_allowed(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "gcovr"))
                self.assertEqual(result.status, Status.ERROR)
                self.assertEqual(
                    result.message,
                    "whether CI reports branch coverage is unknown: some of what it runs could not be read",
                )
                self.assertTrue(result.details[0].startswith("not read: the jobs and commands:"), result.details)
                self.assertEqual(result.details[-1], "--allow-unknown judges only what could be read")
                allowed = self._run(ci_running(provider, "gcovr"), ALLOW_UNKNOWN)
                self.assertEqual(allowed.message, "no branch coverage reporting found in what CI runs")

    def test_branch_coverage_without_path_coverage_suggests_it(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "lcov --rc branch_coverage=1 --capture"))
                self.assertEqual(result, Result.passed("branch coverage is reported with lcov", C_PATH_HINT))

    def test_path_coverage_is_reported_as_a_bonus(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(
            result.message, "branch coverage is reported with gcovr; path coverage bonus: gcc -fcondition-coverage"
        )

    def test_every_gcovr_report_but_the_default_text_counts_branches(self) -> None:
        for options in ("--xml coverage.xml", "--html-details out.html", "--txt-metric branch", "-b", "--sonarqube x"):
            with self.subTest(options=options):
                self.assertEqual(self._run(github_job("ubuntu-latest", f"gcovr {options}")).status, Status.PASS)
        self.assertEqual(self._run(github_job("ubuntu-latest", "gcovr -r .")).status, Status.FAIL)
        configured = {"gcovr.cfg": "# reports\nxml = coverage.xml\n", **github_job("ubuntu-latest", "gcovr")}
        self.assertEqual(self._run(configured).status, Status.PASS)

    def test_gcov_and_llvm_cov(self) -> None:
        for line, expected in (
            ("gcov -b main.gcda", "branch coverage is reported with gcov"),
            ("x86_64-linux-gnu-gcov-14 --branch-counts main.gcda", "branch coverage is reported with gcov"),
            ("llvm-cov gcov -bc main.gcda", "branch coverage is reported with llvm-cov"),
            ("llvm-cov-18 report ./test -instr-profile=x.profdata", "branch coverage is reported with llvm-cov"),
            (
                "llvm-cov show ./test -show-branches=count -show-mcdc",
                "branch coverage is reported with llvm-cov; path coverage bonus: llvm-cov",
            ),
            ("gcov -b --conditions main.gcda", "branch coverage is reported with gcov; path coverage bonus: gcov"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(github_job("ubuntu-latest", line)).message, expected)
        for line in (
            "gcov main.gcda",
            "llvm-cov show ./test",
            "llvm-cov export ./test -show-branch-summary=false",
            "llvm-cov --version",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(github_job("ubuntu-latest", line)).status, Status.FAIL)

    def test_path_coverage_instrumentation_on_the_command_line_or_in_the_cmake_files_configured(self) -> None:
        flags = github_job("ubuntu-latest", "cmake -S . -B b -DCMAKE_CXX_FLAGS='-fcoverage-mcdc'", "llvm-cov report")
        self.assertEqual(
            self._run(flags).message,
            "branch coverage is reported with llvm-cov; path coverage bonus: clang -fcoverage-mcdc",
        )
        cmake = {"CMakeLists.txt": "add_compile_options(-fpath-coverage)\n"}
        configured = self._run({**cmake, **github_job("ubuntu-latest", "cmake -S . -B b", "gcovr --xml x")})
        self.assertEqual(
            configured.message, "branch coverage is reported with gcovr; path coverage bonus: gcc -fpath-coverage"
        )
        # Building does not read the CMake files, and a comment sets nothing.
        commented = {"CMakeLists.txt": "# add_compile_options(-fpath-coverage)\n"}
        for files in (
            {**cmake, **github_job("ubuntu-latest", "cmake --build b", "gcovr --xml x")},
            {**commented, **github_job("ubuntu-latest", "cmake -S . -B b", "gcovr --xml x")},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files), Result.passed("branch coverage is reported with gcovr", C_PATH_HINT))

    def test_launchers_run_the_tool(self) -> None:
        for line in ("uvx gcovr --xml x", "pipx run --spec gcovr gcovr --xml x", "python3 -m gcovr --xml x"):
            with self.subTest(line=line):
                self.assertEqual(self._run(github_job("ubuntu-latest", line)).status, Status.PASS)
        self.assertEqual(self._run(github_job("ubuntu-latest", "npx --yes", "uvx --from gcovr")).status, Status.FAIL)

    def test_python_branch_coverage_does_not_count_for_c_and_cxx(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "coverage run --branch -m pytest --cov-branch"), ALLOW_UNKNOWN)
                self.assertEqual(result.status, Status.FAIL)


class PythonCoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, coverage, files, PYTHON)

    def test_coverage_py_branch_measurement_in_any_ci_passes_without_a_path_coverage_hint(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "python -m coverage run --branch -m pytest"))
                self.assertEqual(result, Result.passed("branch coverage is reported with coverage.py"))

    def test_pytest_cov_branch_passes(self) -> None:
        result = self._run(github_job("ubuntu-latest", "pytest --cov=app --cov-branch"))
        self.assertEqual(result.message, "branch coverage is reported with pytest-cov")

    def test_the_branch_setting_counts_where_coverage_py_reads_it(self) -> None:
        sections = {
            "pyproject.toml": "[tool.coverage.run]",
            ".coveragerc": "[run]",
            "setup.cfg": "[coverage:run]",
            "tox.ini": "[coverage:run]",
        }
        for name, section in sections.items():
            for line in ("coverage run -m pytest", "pytest --cov"):
                with self.subTest(name, line=line):
                    files = {name: f"{section}\nsource = ['app']\nbranch = true\n"}
                    result = self._run({**files, **github_job("ubuntu-latest", line)})
                    self.assertEqual(result.status, Status.PASS)
        named = {"ci/coverage.ini": "[run]\nbranch = on\n", **github_job("x", "coverage run --rcfile=ci/coverage.ini")}
        self.assertEqual(self._run(named).status, Status.PASS)

    def test_a_setting_counts_only_when_ci_runs_what_reads_it(self) -> None:
        setting = {"pyproject.toml": "[tool.coverage.run]\nbranch = true\n"}
        self.assertEqual(self._run(setting).status, Status.FAIL)
        # coverage.py reads .coveragerc, when there is one, and nothing else.
        rc = {**setting, ".coveragerc": "[run]\nsource = app\n", **github_job("ubuntu-latest", "coverage run -m x")}
        self.assertEqual(self._run(rc).status, Status.FAIL)

    def test_pytest_options_from_its_configuration(self) -> None:
        for files in (
            {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = ["--cov=app", "--cov-branch"]\n'},
            {"pytest.ini": "[pytest]\naddopts = --cov=app\n", ".coveragerc": "[run]\nbranch = true\n"},
        ):
            with self.subTest(files=files):
                result = self._run({**files, **github_job("ubuntu-latest", "uv run --with pytest-cov pytest")})
                self.assertEqual(result, Result.passed("branch coverage is reported with pytest-cov"))

    def test_python_runs_a_module_as_its_command(self) -> None:
        for line in (
            "python -u -mcoverage run --branch -m x",
            "python3.12 -W error -X dev -m pytest --cov --cov-branch",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(github_job("ubuntu-latest", line)).status, Status.PASS)
        for line in ("python -c 'import coverage' --branch", "python -m", "python -W error", "python cov.py --branch"):
            with self.subTest(line=line):
                self.assertEqual(self._run(github_job("ubuntu-latest", line)).status, Status.FAIL)

    def test_settings_that_do_not_parse_are_unknown(self) -> None:
        broken = {"setup.cfg": "[coverage:run\nbranch = true\n", **github_job("ubuntu-latest", "coverage run -m x")}
        result = self._run(broken)
        self.assertEqual(result.status, Status.ERROR)
        self.assertTrue(result.details[0].startswith("not read: the coverage.py settings: "), result.details)
        # Settings of tools that do not measure the language's coverage do not matter.
        unrelated = {"phpunit.xml": "<phpunit>", **github_job("ubuntu-latest", "coverage run --branch -m x")}
        self.assertEqual(self._run(unrelated).status, Status.PASS)

    def test_line_coverage_fails(self) -> None:
        result = self._run(
            {**github_job("ubuntu-latest", "coverage run -m pytest"), "setup.cfg": "[coverage:run]\nbranch = false\n"}
        )
        self.assertEqual(
            result,
            Result.failed(
                "no branch coverage reporting found in what CI runs",
                "line coverage is reported with coverage.py",
                "known to report branch coverage: coverage run --branch, pytest --cov --cov-branch",
            ),
        )

    def test_c_and_cxx_branch_coverage_does_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)

    def test_well_configured_python_project_passes(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_PYTHON)).status, Status.PASS)


RUST_PATH_HINT = "consider adding path coverage (e.g. cargo llvm-cov --mcdc, RUSTFLAGS=-Zcoverage-options=mcdc)"


class RustCoverageTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, coverage, files, RUST)

    def test_branch_coverage_tools_in_any_ci_pass_and_suggest_mcdc(self) -> None:
        tools = {
            "cargo-llvm-cov": "cargo +nightly llvm-cov --branch --lcov",
            "cargo-tarpaulin": "cargo tarpaulin --branch --out xml",
            "grcov": "grcov . --binary-path target/debug --branch -o lcov.info",
        }
        for provider in CI_FILES:
            for tool, command in tools.items():
                with self.subTest(ci=provider, tool=tool):
                    result = self._run(ci_running(provider, command))
                    self.assertEqual(result, Result.passed(f"branch coverage is reported with {tool}", RUST_PATH_HINT))

    def test_mcdc_coverage_is_reported_as_a_bonus(self) -> None:
        self.assertEqual(
            self._run(dict(WELL_CONFIGURED_RUST)),
            Result.passed("branch coverage is reported with cargo-llvm-cov; path coverage bonus: cargo-llvm-cov"),
        )
        flags = github_job("ubuntu-latest", 'RUSTFLAGS="-Zcoverage-options=mcdc" cargo +nightly llvm-cov --branch')
        self.assertEqual(self._run(flags).message.rsplit(": ", 1)[1], "rustc MC/DC")

    def test_line_coverage_fails(self) -> None:
        result = self._run(github_job("ubuntu-latest", "cargo llvm-cov --lcov"))
        self.assertEqual(
            result,
            Result.failed(
                "no branch coverage reporting found in what CI runs",
                "line coverage is reported with cargo-llvm-cov",
                "region coverage is reported with cargo-llvm-cov",
                "known to report branch coverage: cargo llvm-cov --branch, cargo tarpaulin --branch, grcov --branch",
            ),
        )


class MixedLanguageCoverageTests(unittest.TestCase):
    def test_every_language_needs_branch_coverage_and_findings_are_labelled(self) -> None:
        result = run_as(self, coverage, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "C/C++: branch coverage is reported with gcovr; path coverage bonus: gcc -fcondition-coverage; "
            "Python: no branch coverage reporting found in what CI runs",
        )

    def test_passes_when_every_language_reports_branch_coverage(self) -> None:
        python = {".github/workflows/python.yml": github_job("x", "coverage run --branch -m x")[GITHUB_WORKFLOW]}
        files = {**WELL_CONFIGURED, **python}
        self.assertEqual(run_as(self, coverage, files, C_AND_CXX, PYTHON).status, Status.PASS)
