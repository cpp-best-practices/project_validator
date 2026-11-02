import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from project_validator.core import Context, Options, Result, Status, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of
from project_validator.text import Pattern, matching_names, pattern

ENABLES_TESTING = (
    pattern("enable_testing()", r"\benable_testing\s*\("),
    pattern("include(CTest)", r"\binclude\s*\(\s*CTest\b"),
)

REGISTERS_TESTS = (
    pattern("add_test", r"\badd_test\s*\("),
    pattern("catch_discover_tests", r"\bcatch_discover_tests\s*\("),
    pattern("gtest_discover_tests", r"\bgtest_discover_tests\s*\("),
    pattern("gtest_add_tests", r"\bgtest_add_tests\s*\("),
    pattern("doctest_discover_tests", r"\bdoctest_discover_tests\s*\("),
    pattern("boost_discover_tests", r"\bboost_discover_tests\s*\("),
)

RUNS_CTEST = (pattern("ctest", r"\bctest\b|--target[\s=]+(test|RUN_TESTS)\b|\bcmake\s+--workflow\b"),)

PYTHON_TEST_FILES = ("test_*.py", "*_test.py")
RUNS_PYTHON_TESTS = (pattern("Python tests", r"\bpytest\b|\bunittest\b|\btox\b|\bnox\b"),)

RUST_TEST = re.compile(r"#\[(?:\w+::)*test\b")
RUNS_RUST_TESTS = (pattern("cargo test", r"\bcargo\s+(\+\S+\s+)?(test|nextest|llvm-cov|tarpaulin)\b"),)


class BuildError(Exception):
    pass


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise BuildError(f"could not run {command[0]}: {error}") from error
    if completed.returncode != 0:
        last_lines = completed.stderr.strip().splitlines()[-5:]
        raise BuildError(f"`{' '.join(command)}` failed: {' | '.join(last_lines)}")
    return completed.stdout


# Multi-config generators (Visual Studio, Ninja Multi-Config) register tests per
# configuration, so ctest lists none unless asked for the configuration that was built.
BUILD_CONFIGURATION = "Debug"


def count_built_tests(root: Path, options: Options) -> int:
    with tempfile.TemporaryDirectory(prefix="project_validator_") as build:
        _run([options.cmake, "-S", str(root), "-B", build, f"-DCMAKE_BUILD_TYPE={BUILD_CONFIGURATION}"])
        _run([options.cmake, "--build", build, "--config", BUILD_CONFIGURATION])
        listing = json.loads(
            _run([options.ctest, "--test-dir", build, "-C", BUILD_CONFIGURATION, "--show-only=json-v1"])
        )
    return len(listing.get("tests", []))


def _built_result(context: Context) -> Result:
    try:
        count = count_built_tests(context.project.root, context.options)
    except BuildError as error:
        return Result.failed(str(error))
    if count == 0:
        return Result.failed("the project configured and built, but ctest found no tests")
    return Result.passed(f"the project builds and ctest finds {count} test(s)")


def _cmake_source_result(context: Context) -> Result:
    if not context.cmake_texts:
        return Result.failed("no CMake files found")
    if not matching_names(context.cmake_texts, ENABLES_TESTING):
        return Result.failed("CTest is never enabled; call enable_testing() or include(CTest)")
    registered = matching_names(context.cmake_texts, REGISTERS_TESTS)
    if not registered:
        return Result.failed("CTest is enabled but no tests are registered")
    return Result.passed(f"CTest is enabled and tests are registered with {', '.join(registered)}")


def _ctest_result(context: Context) -> Result:
    return _built_result(context) if context.options.build else _cmake_source_result(context)


def _python_tests_result(context: Context) -> Result:
    names = (PurePosixPath(path).name for path in context.project.files() if path.endswith(".py"))
    count = sum(1 for name in names if any(fnmatch(name, test_file) for test_file in PYTHON_TEST_FILES))
    if count == 0:
        return Result.failed(f"no Python tests found ({' or '.join(PYTHON_TEST_FILES)} files)")
    return Result.passed(f"Python tests found in {count} file(s)")


def _rust_tests_result(context: Context) -> Result:
    sources = (path for path in context.project.files() if path.endswith(".rs"))
    count = sum(1 for path in sources if RUST_TEST.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no Rust tests found (#[test] functions)")
    return Result.passed(f"Rust tests found in {count} file(s)")


@dataclass(frozen=True, slots=True, kw_only=True)
class TestSuite:
    """How an ecosystem's tests are found, and how CI is recognised running them."""

    found: Callable[[Context], Result]
    runs: tuple[Pattern, ...]
    runner: str


SUITES = {
    C_AND_CXX: TestSuite(found=_ctest_result, runs=RUNS_CTEST, runner="ctest"),
    PYTHON: TestSuite(found=_python_tests_result, runs=RUNS_PYTHON_TESTS, runner="pytest, unittest, tox or nox"),
    RUST: TestSuite(found=_rust_tests_result, runs=RUNS_RUST_TESTS, runner="cargo test"),
}


def _run_in_ci(suite: TestSuite, context: Context) -> Result:
    result = suite.found(context)
    if result.status != Status.PASS or matching_names(context.ci_texts, suite.runs):
        return result
    return Result.warned(f"{result.message}, but no CI configuration runs {suite.runner}", *result.details)


@check(
    name="ctest-runs",
    description="Tests exist (registered with CTest for C/C++) and CI runs them",
    languages=languages_of(SUITES),
)
def ctest_runs(context: Context) -> Result:
    return check_each_ecosystem(context, SUITES, _run_in_ci)
