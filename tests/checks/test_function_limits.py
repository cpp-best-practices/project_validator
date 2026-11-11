from __future__ import annotations

import unittest

from project_validator.checks.function_limits import function_limits
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.facts import Facts
from project_validator.facts.limits import FUNCTION_LENGTH, LIMITS
from project_validator.policy.limits import judge_limits
from project_validator.questions.tooling import tool_answer
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    run_as,
    run_in_every_layout,
)

CLANG_TIDY = """\
Checks: '-*,readability-function-size'
CheckOptions:
  - key: readability-function-size.LineThreshold
    value: 80
"""
RUNS_CLANG_TIDY = github_job("x", "run-clang-tidy -p build")
HINT = (
    "consider running in CI: clang-tidy with readability-function-size and a LineThreshold in .clang-tidy "
    "or lizard --length 30"
)
LIZARD_HINT = "consider running in CI: lizard --length 30"
NEVER_LIMITED = Result.failed("function length is never limited", HINT)
CLANG_TIDY_WITHOUT_LIMIT = Result.failed(
    "CI runs clang-tidy's readability-function-size, but without a function length limit; "
    "set readability-function-size with a LineThreshold or StatementThreshold in .clang-tidy"
)
LIMITED_BY_CLANG_TIDY = Result.passed(
    "function length is limited with clang-tidy's readability-function-size (.clang-tidy)"
)
LIMITED_BY_LIZARD = Result.passed("function length is limited with lizard")


class FunctionLimitsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, function_limits, files, c_family_layouts_built_with(function_limits, "CMake"))

    def test_applies_to_the_languages_its_limiters_measure(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust", "Go", "C#"}, function_limits.languages)
        # No known tool limits the length of F# functions.
        self.assertNotIn("F#", function_limits.languages)

    def test_fails_without_function_limits(self) -> None:
        self.assertEqual(self._run(BARE_PROJECT), NEVER_LIMITED)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.PASS)
        self.assertIn("clang-tidy's readability-function-size", self._run(WELL_CONFIGURED).message)

    def test_lizard_length_limits_in_any_spelling_count(self) -> None:
        for command in (
            "lizard src -L 60 -w",
            "lizard -L60",
            "lizard --length=60",
            "lizard --length 60",
            "lizard -Tnloc=40",
            "lizard -T length=60",
            "lizard --Threshold length=60",
            "lizard --Threshold=nloc=60",
            "python -m lizard -L 30",
            "lizard src \\\n  -L 60",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._run(github_job("x", command)), LIMITED_BY_LIZARD)

    def test_lizard_in_any_ci_counts(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                self.assertEqual(self._run(ci_running(provider, "lizard -L 60 src")).status, Status.PASS)

    def test_lizard_without_a_length_limit_does_not_count(self) -> None:
        for command in ("lizard src", "lizard -l cpp src", "lizard -C 10 src", "lizard -L many", "lizard -T ccn=5"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(github_job("x", command)),
                    Result.failed("CI runs lizard, but without a function length limit; set a --length limit"),
                )

    def test_what_ci_configuration_that_is_not_parsed_hides_is_an_error(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, "make lint"))
                self.assertEqual(result.status, Status.ERROR)
                self.assertEqual(
                    result.message,
                    "whether CI limits function length is unknown: some of what it runs could not be read",
                )

    def test_passes_when_cmake_runs_clang_tidy(self) -> None:
        cmake = {"CMakeLists.txt": "set(CMAKE_CXX_CLANG_TIDY clang-tidy)\n", **github_job("x", "cmake -B build")}
        result = self._run({".clang-tidy": CLANG_TIDY, **cmake})
        self.assertEqual(
            result,
            Result.passed("function length is limited with clang-tidy's readability-function-size (.clang-tidy)"),
        )

    def test_line_or_statement_thresholds_in_either_options_style_count(self) -> None:
        for clang_tidy in (
            CLANG_TIDY,
            "Checks: [readability-*]\nCheckOptions:\n  readability-function-size.StatementThreshold: '50'\n",
        ):
            with self.subTest(clang_tidy=clang_tidy):
                self.assertEqual(self._run({".clang-tidy": clang_tidy, **RUNS_CLANG_TIDY}), LIMITED_BY_CLANG_TIDY)

    def test_warns_when_nothing_runs_clang_tidy(self) -> None:
        self.assertEqual(
            self._run({".clang-tidy": CLANG_TIDY}),
            Result.warned(
                ".clang-tidy limits function length, but CI does not run clang-tidy's readability-function-size", HINT
            ),
        )

    def test_a_check_that_is_off_or_has_no_threshold_limits_nothing(self) -> None:
        for clang_tidy in (
            CLANG_TIDY.replace("'-*,readability-function-size'", "'-*,bugprone-*'"),
            CLANG_TIDY.replace("'-*,readability-function-size'", "'readability-*,-readability-function-size'"),
            CLANG_TIDY.replace("'-*,readability-function-size'", "''"),
            "Checks: 'readability-function-size'\n",
            "Checks: 'readability-function-size'\nCheckOptions:\n  readability-function-size.LineThreshold: -1\n",
            "CheckOptions:\n  readability-function-size.LineThreshold: 80\n",
            "Checks: 'readability-function-size'\nCheckOptions:\n  - key\n",
        ):
            with self.subTest(clang_tidy=clang_tidy):
                self.assertEqual(self._run({".clang-tidy": clang_tidy, **RUNS_CLANG_TIDY}), CLANG_TIDY_WITHOUT_LIMIT)

    def test_an_unreadable_clang_tidy_file_is_unknown(self) -> None:
        result = self._run({".clang-tidy": "Checks: [\n", **RUNS_CLANG_TIDY})
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("not read: the clang-tidy settings", result.details[0])

    def test_a_language_no_known_tool_measures_is_skipped(self) -> None:
        answer = tool_answer(FUNCTION_LENGTH, LIMITS, "Lang", Facts(()), ())
        self.assertEqual(
            judge_limits(answer),
            Result(status=Status.SKIP, message="no known tool limits the length of Lang functions"),
        )


class OtherLanguageFunctionLimitsTests(unittest.TestCase):
    NEVER_LIMITED = Result.failed("function length is never limited", LIZARD_HINT)

    def test_a_lizard_length_limit_passes(self) -> None:
        for ecosystem in (PYTHON, RUST):
            for provider in CI_FILES:
                with self.subTest(ecosystem=ecosystem.label, ci=provider):
                    result = run_as(self, function_limits, ci_running(provider, "lizard --length 30 src"), ecosystem)
                    self.assertEqual(result, LIMITED_BY_LIZARD)

    def test_fails_without_a_lizard_length_limit(self) -> None:
        for ecosystem in (PYTHON, RUST):
            for command in ("pytest", "cargo clippy"):
                with self.subTest(ecosystem=ecosystem.label, command=command):
                    self.assertEqual(
                        run_as(self, function_limits, github_job("x", command), ecosystem), self.NEVER_LIMITED
                    )

    def test_clang_tidy_does_not_count(self) -> None:
        files = {".clang-tidy": CLANG_TIDY, **RUNS_CLANG_TIDY}
        self.assertEqual(run_as(self, function_limits, files, PYTHON), self.NEVER_LIMITED)

    def test_well_configured_projects_pass(self) -> None:
        for ecosystem, files in ((PYTHON, WELL_CONFIGURED_PYTHON), (RUST, WELL_CONFIGURED_RUST)):
            with self.subTest(ecosystem=ecosystem.label):
                self.assertEqual(run_as(self, function_limits, dict(files), ecosystem), LIMITED_BY_LIZARD)


class MixedLanguageFunctionLimitsTests(unittest.TestCase):
    def test_every_language_needs_a_limit_and_findings_are_labelled(self) -> None:
        result = run_as(self, function_limits, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "C/C++: function length is limited with clang-tidy's readability-function-size (.clang-tidy); "
            "Python: function length is never limited",
        )

    def test_one_lizard_length_limit_covers_every_language(self) -> None:
        result = run_as(self, function_limits, github_job("x", "lizard -L 30"), C_AND_CXX, PYTHON)
        # The same result for every ecosystem is said once.
        self.assertEqual(result, LIMITED_BY_LIZARD)
