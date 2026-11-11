"""The Dart profile's rules, judged by the generic checks in the Dart package and Flutter application layouts."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.dart import DART_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, run_as, temp_project

TEST = {"test/shop_test.dart": "import 'package:test/test.dart';\n\nvoid main() {\n  test('adds', () {});\n}\n"}
RECOMMENDED = {"analysis_options.yaml": "include: package:lints/recommended.yaml\n"}
APPLICATION = {
    "pubspec.yaml": "name: shop\npublish_to: none\nenvironment:\n  sdk: ^3.5.0\ndependencies:\n  args: ^2.6.0\n"
}
PACKAGE = {"pubspec.yaml": "name: shop\nversion: 1.0.0\nenvironment:\n  sdk: ^3.5.0\ndependencies:\n  args: ^2.6.0\n"}
DART_SDK_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest]
            sdk: ["3.5", stable]
        steps:
          - uses: dart-lang/setup-dart@v1
            with:
              sdk: ${{ matrix.sdk }}
          - run: dart test
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_a_pub_workspace_has_a_package_per_unit(self) -> None:
        files = {
            "pubspec.yaml": "name: _\nenvironment:\n  sdk: ^3.6.0\nworkspace:\n  - packages/core\n  - packages/app\n",
            "packages/core/pubspec.yaml": "name: core\nresolution: workspace\n",
            "packages/core/lib/core.dart": "",
            "packages/app/pubspec.yaml": "name: app\nresolution: workspace\n",
            "packages/app/lib/main.dart": "",
        }
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Dart"}))
        self.assertEqual(sorted(unit.directory for unit in structure.units), [".", "packages/app", "packages/core"])
        with temp_project({"pubspec.yaml": "workspace: [", "lib/a.dart": ""}) as root:
            self.assertEqual([unit.directory for unit in make_context(root).structure.units], ["."])

    def test_a_build_directory_beside_a_pubspec_is_never_read(self) -> None:
        with temp_project({"pubspec.yaml": "name: shop\n", "lib/a.dart": "", "build/app.apk": ""}) as root:
            self.assertNotIn("build/app.apk", make_context(root).project.files())

    def test_ci_usage(self) -> None:
        for text in (
            "dart test",
            "flutter analyze",
            "uses: dart-lang/setup-dart@v1",
            "uses: subosito/flutter-action@v2",
        ):
            with self.subTest(text=text):
                self.assertTrue(DART_ECOSYSTEM.used_by(text))
        self.assertFalse(DART_ECOSYSTEM.used_by("npm test"))


class DartTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, DART_ECOSYSTEM)

    def test_tests_run_by_dart_or_flutter_test(self) -> None:
        for command in ("dart test", "flutter test", "dart run test", "very_good test"):
            with self.subTest(command=command):
                self.assertEqual(self._run(tests_run, {**TEST, **_ci(command)}).status, Status.PASS)
        widgets = {"test/widget_test.dart": "void main() {\n  testWidgets('renders', (tester) async {});\n}\n"}
        self.assertEqual(self._run(tests_run, {**widgets, **_ci("flutter test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TEST, **_ci("dart analyze")}).status, Status.WARN)
        helper = {"test/helpers.dart": "void setUpAll() {}\n", **_ci("dart test")}
        self.assertEqual(self._run(tests_run, helper).status, Status.FAIL)

    def test_coverage_needs_branch_coverage(self) -> None:
        for command in (
            "dart test --coverage=coverage --branch-coverage",
            "flutter test --coverage --branch-coverage",
            "dart run coverage:test_with_coverage --branch-coverage",
        ):
            with self.subTest(command=command):
                result = self._run(coverage, _ci(command))
                self.assertEqual(result, Result.passed("branch coverage is reported with dart test --coverage"))
        for command in ("dart test --coverage=coverage", "flutter test --coverage", "very_good test --coverage"):
            with self.subTest(command=command):
                self.assertEqual(self._run(coverage, _ci(command)).status, Status.FAIL)
        self.assertEqual(self._run(coverage, _ci("dart test", "very_good test")).status, Status.FAIL)

    def test_dart_format_enforces_when_it_sets_the_exit_code(self) -> None:
        for command in ("dart format --output=none --set-exit-if-changed .", "dart format --set-exit-if-changed lib"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(code_formatting, _ci(command)), Result.passed("CI enforces the dart format style")
                )
        self.assertEqual(self._run(code_formatting, _ci("dart format .")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("dart format --output=none .")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("dart format -o show .")).status, Status.FAIL)

    def test_a_lint_set_and_dart_analyze_are_the_warning_set(self) -> None:
        result = self._run(compiler_warnings, {**RECOMMENDED, **_ci("dart analyze")})
        expected = "strict Dart analyzer settings are enabled: a lint set in analysis_options.yaml, dart analyze"
        self.assertEqual(result, Result.passed(expected))
        for include in ("package:flutter_lints/flutter.yaml", "package:very_good_analysis/analysis_options.yaml"):
            with self.subTest(include=include):
                files = {"analysis_options.yaml": f"include: {include}\n", **_ci("flutter analyze")}
                self.assertEqual(self._run(compiler_warnings, files).status, Status.PASS)
        self.assertEqual(self._run(compiler_warnings, _ci("dart analyze")).status, Status.WARN)
        self.assertEqual(self._run(compiler_warnings, {**RECOMMENDED, **_ci("dart test")}).status, Status.WARN)
        core = {"analysis_options.yaml": "include: package:lints/core.yaml\n", **_ci("dart analyze")}
        self.assertEqual(self._run(compiler_warnings, core).status, Status.WARN)

    def test_fatal_infos_make_the_lints_errors(self) -> None:
        self.assertEqual(self._run(warnings_as_errors, _ci("dart analyze --fatal-infos")).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("flutter analyze --fatal-infos .")).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("dart analyze")).status, Status.FAIL)

    def test_dart_analyze_custom_lint_and_dcm_are_static_analysis(self) -> None:
        self.assertEqual(
            self._run(static_analysis, {**RECOMMENDED, **_ci("dart analyze")}),
            Result.passed("dart analyze (analysis_options.yaml) runs"),
        )
        self.assertEqual(self._run(static_analysis, _ci("flutter analyze")), Result.passed("dart analyze runs"))
        self.assertEqual(self._run(static_analysis, _ci("dart run custom_lint")).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, _ci("dcm analyze lib")).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, _ci("dart test")).status, Status.FAIL)

    def test_semgrep_scans_but_codeql_does_not(self) -> None:
        self.assertEqual(self._run(security_scanning, _ci("semgrep ci")).status, Status.PASS)
        self.assertEqual(
            self._run(security_scanning, github_steps("uses: github/codeql-action/analyze@v3")).status, Status.WARN
        )

    def test_osv_scanner_and_trivy_read_the_lockfile_but_snyk_does_not(self) -> None:
        for command in ("osv-scanner -r .", "trivy fs ."):
            with self.subTest(command=command):
                self.assertEqual(self._run(dependency_audit, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(dependency_audit, _ci("snyk test")).status, Status.WARN)

    def test_an_application_commits_its_lockfile_and_a_package_leaves_it_out(self) -> None:
        result = self._run(dependency_management, APPLICATION)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("pubspec.lock", " ".join(result.details))
        self.assertEqual(
            self._run(dependency_management, {**APPLICATION, "pubspec.lock": "packages: {}\n"}).status, Status.PASS
        )
        self.assertEqual(self._run(dependency_management, PACKAGE).status, Status.PASS)
        broken = {"pubspec.yaml": "dependencies: [\n"}
        self.assertEqual(self._run(dependency_management, broken).status, Status.ERROR)

    def test_dart_tool_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": ".dart_tool/\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "build/\ncoverage/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_dart_or_flutter_sdks(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: DART_SDK_MATRIX})
        self.assertIn("2 Dart or Flutter SDK version(s) (Dart 3.5, Dart stable)", result.message)
        flutter = github_steps("uses: subosito/flutter-action@v2", "run: flutter test")
        flutter[GITHUB_WORKFLOW] = flutter[GITHUB_WORKFLOW].replace(
            '"uses": "subosito/flutter-action@v2"',
            '"uses": "subosito/flutter-action@v2", "with": {"flutter-version": "3.24.0"}',
        )
        self.assertIn("(Flutter 3.24.0)", self._run(platform_matrix, flutter).message)
        image = {
            GITHUB_WORKFLOW: "jobs:\n  test:\n    runs-on: ubuntu-latest\n    container: dart:3.5\n"
            "    steps:\n      - run: dart test\n"
        }
        self.assertIn("(Dart 3.5)", self._run(platform_matrix, image).message)
        self.assertIn("(default)", self._run(platform_matrix, _ci("flutter test")).message)
