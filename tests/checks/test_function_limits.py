import unittest

from project_validator.checks.function_limits import function_limits
from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)


class FunctionLimitsTests(unittest.TestCase):
    CLANG_TIDY = """\
        Checks: '-*,readability-function-size'
        CheckOptions:
          - key: readability-function-size.LineThreshold
            value: 80
        """
    RUNS_CLANG_TIDY = {GITHUB_WORKFLOW: "steps:\n  - run: run-clang-tidy -p build\n"}
    NEVER_LIMITED = (
        "function length is never limited; enable clang-tidy readability-function-size with a LineThreshold "
        "or run lizard --length 30 in CI"
    )

    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, function_limits, files)

    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(function_limits.languages, C_FAMILY | {"Python", "Rust"})

    def test_fails_without_function_limits(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result, Result.failed(self.NEVER_LIMITED))

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(WELL_CONFIGURED)
        expected = Result.passed(
            "function length is limited with clang-tidy readability-function-size (LineThreshold 80)"
        )
        self.assertEqual(result, expected)

    def test_passes_with_a_lizard_length_limit_in_any_ci(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                result = self._run({path: "steps:\n  - run: lizard src -L 60 -w\n"})
                self.assertEqual(result, Result.passed("function length is limited with lizard -L 60"))

    def test_lizard_threshold_spellings_count(self) -> None:
        for command, limit in (
            ("lizard --length=60", "--length=60"),
            ("lizard -Tnloc=40", "-Tnloc=40"),
            ("lizard --Threshold length=60", "--Threshold length=60"),
        ):
            with self.subTest(command=command):
                result = self._run({".gitlab-ci.yml": f"lint:\n  script:\n    - {command}\n"})
                self.assertEqual(result, Result.passed(f"function length is limited with lizard {limit}"))

    def test_lizard_options_on_continuation_lines_count(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "steps:\n  - run: |\n      lizard src \\\n        -L 60\n"})
        self.assertEqual(result, Result.passed("function length is limited with lizard -L 60"))

    def test_lizard_without_a_length_limit_does_not_count(self) -> None:
        for command in ("lizard src", "lizard -l cpp src", "lizard -C 10 src"):
            with self.subTest(command=command):
                result = self._run({GITHUB_WORKFLOW: f"steps:\n  - run: {command}\n"})
                self.assertEqual(result, Result.failed(self.NEVER_LIMITED))

    def test_passes_when_cmake_runs_clang_tidy(self) -> None:
        result = self._run({".clang-tidy": self.CLANG_TIDY, "CMakeLists.txt": "set(CMAKE_CXX_CLANG_TIDY clang-tidy)\n"})
        self.assertEqual(result.status, Status.PASS)

    def test_statement_threshold_and_mapping_style_options_count(self) -> None:
        clang_tidy = "Checks: [readability-*]\nCheckOptions:\n  readability-function-size.StatementThreshold: '50'\n"
        result = self._run({".clang-tidy": clang_tidy, **self.RUNS_CLANG_TIDY})
        expected = Result.passed(
            "function length is limited with clang-tidy readability-function-size (StatementThreshold 50)"
        )
        self.assertEqual(result, expected)

    def test_warns_when_nothing_runs_clang_tidy(self) -> None:
        result = self._run({".clang-tidy": self.CLANG_TIDY})
        expected = Result.warned(
            "function length limits are configured for clang-tidy readability-function-size (LineThreshold 80) "
            "but nothing runs clang-tidy",
            "run clang-tidy in CI, or set CMAKE_CXX_CLANG_TIDY",
        )
        self.assertEqual(result, expected)

    def test_disabled_check_does_not_count(self) -> None:
        for checks in ("'-*,bugprone-*'", "'readability-*,-readability-function-size'", "''"):
            with self.subTest(checks=checks):
                clang_tidy = self.CLANG_TIDY.replace("'-*,readability-function-size'", checks)
                result = self._run({".clang-tidy": clang_tidy, **self.RUNS_CLANG_TIDY})
                expected = Result.failed(
                    self.NEVER_LIMITED, "readability-function-size is not enabled by the Checks in .clang-tidy"
                )
                self.assertEqual(result, expected)

    def test_enabled_check_without_a_length_threshold_fails_and_says_why(self) -> None:
        for options in ("", "CheckOptions:\n  readability-function-size.LineThreshold: -1\n"):
            with self.subTest(options=options):
                clang_tidy = f"Checks: 'readability-function-size'\n{options}"
                result = self._run({".clang-tidy": clang_tidy, **self.RUNS_CLANG_TIDY})
                expected = Result.failed(
                    self.NEVER_LIMITED,
                    "readability-function-size is enabled in .clang-tidy but sets no LineThreshold or "
                    "StatementThreshold",
                )
                self.assertEqual(result, expected)

    def test_unreadable_clang_tidy_file_does_not_count(self) -> None:
        result = self._run({".clang-tidy": "Checks: [\n", **self.RUNS_CLANG_TIDY})
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn(".clang-tidy could not be read", " ".join(result.details))


class OtherLanguageFunctionLimitsTests(unittest.TestCase):
    NEVER_LIMITED = Result.failed("function length is never limited; run lizard --length 30 in CI")

    def test_lizard_length_limit_in_any_ci_passes(self) -> None:
        for ecosystem in (PYTHON, RUST):
            for provider, path in CI_FILES.items():
                with self.subTest(ecosystem=ecosystem.label, ci=provider):
                    result = run_as(self, function_limits, {path: "script: lizard --length 30 src\n"}, ecosystem)
                    self.assertEqual(result, Result.passed("function length is limited with lizard --length 30"))

    def test_fails_without_a_lizard_length_limit(self) -> None:
        for ecosystem in (PYTHON, RUST):
            for command in ("pytest", "lizard src", "cargo clippy"):
                with self.subTest(ecosystem=ecosystem.label, command=command):
                    result = run_as(self, function_limits, {GITHUB_WORKFLOW: f"run: {command}\n"}, ecosystem)
                    self.assertEqual(result, self.NEVER_LIMITED)

    def test_clang_tidy_does_not_count(self) -> None:
        files = {".clang-tidy": FunctionLimitsTests.CLANG_TIDY, **FunctionLimitsTests.RUNS_CLANG_TIDY}
        self.assertEqual(run_as(self, function_limits, files, PYTHON), self.NEVER_LIMITED)

    def test_well_configured_projects_pass(self) -> None:
        for ecosystem, files in ((PYTHON, WELL_CONFIGURED_PYTHON), (RUST, WELL_CONFIGURED_RUST)):
            with self.subTest(ecosystem=ecosystem.label):
                result = run_as(self, function_limits, dict(files), ecosystem)
                self.assertEqual(result, Result.passed("function length is limited with lizard --length 30"))


class MixedLanguageFunctionLimitsTests(unittest.TestCase):
    def test_every_language_needs_a_limit_and_findings_are_labelled(self) -> None:
        result = run_as(self, function_limits, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        expected = Result.failed(
            "C/C++: function length is limited with clang-tidy readability-function-size (LineThreshold 80); "
            "Python: function length is never limited; run lizard --length 30 in CI"
        )
        self.assertEqual(result, expected)

    def test_one_lizard_length_limit_covers_every_language(self) -> None:
        result = run_as(self, function_limits, {GITHUB_WORKFLOW: "run: lizard -L 30\n"}, C_AND_CXX, PYTHON)
        expected = Result.passed(
            "C/C++: function length is limited with lizard -L 30; Python: function length is limited with lizard -L 30"
        )
        self.assertEqual(result, expected)
