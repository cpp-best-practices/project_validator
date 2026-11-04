"""C/C++ tests: registered with CTest in CMake files, or listed by ctest after a real build with --build."""

import json
import subprocess
import tempfile
from pathlib import Path

from project_validator.core import Context, Options, Result
from project_validator.rules import TestSuite
from project_validator.text import matching_names, pattern

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


class BuildError(Exception):
    pass


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 - argv list, no shell
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


CTEST = TestSuite(found=_ctest_result, runs=RUNS_CTEST, runner="ctest")
