"""The Swift profile's rules, judged by the generic checks in the SwiftPM and Xcode project layouts."""

from __future__ import annotations

import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems.swift import (
    SWIFT,
    SWIFTLINT_TOOL,
    SWIFTPM_PACKAGES,
    swiftpm_build_types,
    xcode_build_types,
)
from project_validator.facts import Facts, Origin, Setting
from tests.support import (
    GITHUB_WORKFLOW,
    checks_named,
    command,
    github_job,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
)
from tests.support import command as shell_command

(
    CODE_FORMATTING,
    COMMITTED_ARTIFACTS,
    COMPILER_WARNINGS,
    COVERAGE,
    DEPENDENCY_MANAGEMENT,
    FUNCTION_LIMITS,
    HARDENING,
    PLATFORM_MATRIX,
    TESTS_RUN,
    VCS_IGNORE,
    WARNINGS_AS_ERRORS,
) = checks_named(
    "code-formatting",
    "committed-artifacts",
    "compiler-warnings",
    "coverage",
    "dependency-management",
    "function-limits",
    "hardening",
    "platform-matrix",
    "tests-run",
    "vcs-ignore",
    "warnings-as-errors",
)
SWIFTPM = "SwiftPM"
XCODE = "Xcode Swift"
PBXPROJ = "App.xcodeproj/project.pbxproj"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("macos-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_an_xcode_project_directory_is_a_build_system(self) -> None:
        with temp_project({"App.xcworkspace/contents.xcworkspacedata": "", "App/View.swift": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (frozenset({"Swift"}), frozenset({"Xcode"})))

    def test_swiftpm_and_xcode_configurations_are_build_types(self) -> None:
        self.assertEqual(swiftpm_build_types(command("swift build")), {"debug"})
        self.assertEqual(swiftpm_build_types(command("swift test -c release")), {"release"})
        self.assertEqual(swiftpm_build_types(command("swift build --configuration=release")), {"release"})
        self.assertEqual(swiftpm_build_types(command("swift package resolve")), set())
        self.assertEqual(xcode_build_types(command("xcodebuild -scheme App -configuration Debug test")), {"debug"})
        # Without -configuration, the scheme decides, which CI configuration does not show.
        self.assertEqual(xcode_build_types(command("xcodebuild -scheme App test")), set())


class ToolTests(unittest.TestCase):
    def test_formatters_must_fail_on_findings(self) -> None:
        for line in ("swift-format lint -s -r Sources", "swift format lint --strict -r .", "swiftformat --lint ."):
            with self.subTest(line=line):
                self.assertEqual(run_as(self, CODE_FORMATTING, _ci(line), SWIFT).status, Status.PASS)
        self.assertEqual(run_as(self, CODE_FORMATTING, _ci("swift format lint -r ."), SWIFT).status, Status.FAIL)
        rewritten = run_as(self, CODE_FORMATTING, _ci("swift format -i -r Sources"), SWIFT)
        self.assertEqual(rewritten.status, Status.FAIL)
        self.assertIn("CI runs swift-format but only to rewrite files", rewritten.message)
        committed = _ci("swift format -i -r Sources", "git diff --exit-code")
        self.assertEqual(run_as(self, CODE_FORMATTING, committed, SWIFT).status, Status.PASS)

    def test_tests_are_xctest_cases_or_swift_testing_functions(self) -> None:
        xctest = {"Tests/AppTests/AppTests.swift": "final class AppTests: XCTestCase {}\n"}
        result = run_in_layout(self, SWIFTPM, TESTS_RUN, {**xctest, **_ci("swift test")})
        self.assertEqual(
            result,
            Result.passed(
                "XCTestCase classes or Swift Testing @Test functions: 1 file(s), run by swift test or xcodebuild test"
            ),
        )
        xcode = {"AppTests/Tests.swift": "@Test func adds() {}\n", **_ci("xcodebuild -scheme App test")}
        self.assertEqual(run_in_layout(self, XCODE, TESTS_RUN, xcode).status, Status.PASS)
        self.assertEqual(run_in_layout(self, SWIFTPM, TESTS_RUN, {}).status, Status.FAIL)

    def test_coverage_counts_regions(self) -> None:
        expected = Result.passed(
            "region coverage is measured with swift test",
            "consider reporting region coverage where it can be seen (a report CI publishes, a coverage service)",
            "consider failing CI when region coverage falls below a threshold",
        )
        self.assertEqual(run_in_layout(self, SWIFTPM, COVERAGE, _ci("swift test --enable-code-coverage")), expected)
        enabled = '<Scheme><TestAction codeCoverageEnabled = "YES"/></Scheme>'
        scheme = {"App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": enabled}
        for files in (
            {**scheme, **_ci("xcodebuild -scheme App test")},
            _ci("xcodebuild test -scheme Other -enableCodeCoverage YES"),
        ):
            with self.subTest(files=files):
                result = run_in_layout(self, XCODE, COVERAGE, files)
                self.assertEqual(
                    result,
                    Result.passed(
                        "region coverage is measured with Xcode",
                        "consider reporting region coverage where it can be seen (a report CI publishes, a coverage "
                        "service)",
                        "consider failing CI when region coverage falls below a threshold",
                    ),
                )
        # The scheme counts when CI tests with it.
        for files in (scheme, _ci("xcodebuild test"), {**scheme, **_ci("xcodebuild -scheme Other test")}):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, XCODE, COVERAGE, files).status, Status.FAIL)

    def test_swiftlint_and_complete_concurrency_checking(self) -> None:
        swift6 = run_in_layout(self, SWIFTPM, COMPILER_WARNINGS, _ci("swiftlint --strict"))
        self.assertEqual(
            swift6, Result.passed("strict Swift warning settings are enabled: SwiftLint, complete concurrency checking")
        )
        xcode = {PBXPROJ: "SWIFT_STRICT_CONCURRENCY = complete;", **_ci("swiftlint lint")}
        self.assertEqual(run_in_layout(self, XCODE, COMPILER_WARNINGS, xcode).status, Status.PASS)
        swift5 = {"Package.swift": "// swift-tools-version:5.10\n", **_ci("swiftlint --fix")}
        self.assertEqual(run_in_layout(self, SWIFTPM, COMPILER_WARNINGS, swift5).status, Status.FAIL)

    def test_warnings_as_errors_in_swiftpm_or_xcode(self) -> None:
        for layout, files in (
            (SWIFTPM, {"Package.swift": "swiftSettings: [.treatAllWarnings(as: .error)]\n"}),
            (XCODE, {PBXPROJ: "SWIFT_TREAT_WARNINGS_AS_ERRORS = YES;"}),
        ):
            with self.subTest(layout=layout):
                self.assertEqual(run_in_layout(self, layout, WARNINGS_AS_ERRORS, files).status, Status.PASS)

    def test_warnings_as_errors_in_bazels_copts(self) -> None:
        """SwiftLint's: `-warnings-as-errors` in a Starlark macro's copts (bazel/copts.bzl), or a BUILD file's
        (upstream #207)."""
        module = {"MODULE.bazel": 'module(name = "shop")\n', "Sources/Shop/Shop.swift": "let shop = 1\n"}
        for files in (
            {"bazel/copts.bzl": 'COPTS = [\n    "-warnings-as-errors",\n]\n'},
            {"BUILD.bazel": 'swift_library(name = "shop", copts = ["-warnings-as-errors"])\n'},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, {**module, **files}, SWIFT).status, Status.PASS)
        self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, module, SWIFT).status, Status.FAIL)


class SafetyTests(unittest.TestCase):
    def test_runtime_safety_checks_must_not_be_compiled_away(self) -> None:
        self.assertEqual(run_as(self, HARDENING, _ci("swift build -c release"), SWIFT).status, Status.PASS)
        for files in (
            _ci("swift build -c release -Xswiftc -enforce-exclusivity=unchecked"),
            {PBXPROJ: 'SWIFT_OPTIMIZATION_LEVEL = "-Ounchecked";'},
        ):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, XCODE, HARDENING, files).status, Status.FAIL)

    def test_function_body_length_is_on_unless_disabled(self) -> None:
        expected = Result.passed("function length is limited with SwiftLint's function_body_length")
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("swiftlint"), SWIFT), expected)
        for config in (
            "function_body_length:\n  warning: 40\n",
            "only_rules:\n  - function_body_length\n",
            "disabled_rules:\n  - line_length\n",
        ):
            with self.subTest(config=config):
                files = {".swiftlint.yml": config, **_ci("swiftlint")}
                self.assertEqual(run_as(self, FUNCTION_LIMITS, files, SWIFT).status, Status.PASS)
        for config in (
            "disabled_rules:\n  - line_length\n  - function_body_length\n",
            "only_rules:\n  - line_length\n",
        ):
            with self.subTest(config=config):
                files = {".swiftlint.yml": config, **_ci("swiftlint")}
                self.assertEqual(run_as(self, FUNCTION_LIMITS, files, SWIFT).status, Status.FAIL)
        self.assertEqual(run_as(self, FUNCTION_LIMITS, {}, SWIFT).status, Status.FAIL)


class DependencyAndOutputTests(unittest.TestCase):
    PACKAGE = '.package(url: "https://github.com/apple/swift-log", from: "1.6.0")'

    def test_an_application_commits_package_resolved(self) -> None:
        app = {"Package.swift": f'dependencies: [{self.PACKAGE}], targets: [.executableTarget(name: "App")]\n'}
        expected = Result.warned(
            "dependencies are declared in Package.swift (SwiftPM) but not locked", SWIFTPM_PACKAGES.lock_hint
        )
        self.assertEqual(run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, app), expected)
        locked = run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, {**app, "Package.resolved": "{}"})
        self.assertEqual(
            locked.message, "dependencies are declared in Package.swift (SwiftPM) and locked in Package.resolved"
        )

    def test_a_library_need_not(self) -> None:
        library = {"Package.swift": f'dependencies: [{self.PACKAGE}], targets: [.target(name: "Lib")]\n'}
        self.assertEqual(
            run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, library),
            Result.passed("dependencies are declared in Package.swift (SwiftPM)"),
        )

    def test_an_xcode_app_with_swiftpm_packages_locks_them(self) -> None:
        files = {"Package.swift": f"dependencies: [{self.PACKAGE}]\n", PBXPROJ: ""}
        self.assertEqual(run_in_layout(self, XCODE, DEPENDENCY_MANAGEMENT, files).status, Status.WARN)

    def test_each_build_system_ignores_its_own_output(self) -> None:
        self.assertEqual(run_in_layout(self, SWIFTPM, VCS_IGNORE, {".gitignore": ".build\n"}).status, Status.PASS)
        self.assertEqual(run_in_layout(self, XCODE, VCS_IGNORE, {".gitignore": "xcuserdata/\n"}).status, Status.PASS)
        self.assertEqual(run_in_layout(self, XCODE, VCS_IGNORE, {".gitignore": ".build/\n"}).status, Status.WARN)
        committed = run_in_layout(
            self, XCODE, COMMITTED_ARTIFACTS, {"App.xcodeproj/xcuserdata/me.xcuserdatad/x.plist": ""}
        )
        self.assertEqual(committed.message, "1 build output is committed")

    def test_the_platform_matrix_counts_swift_and_xcode_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  linux:
                    runs-on: ubuntu-latest
                    container: swift:6.1
                    steps:
                      - run: swift test
                  macos:
                    runs-on: macos-15
                    env:
                      DEVELOPER_DIR: /Applications/Xcode_16.4.app/Contents/Developer
                    steps:
                      - run: swift test
                """
        }
        self.assertIn("2 Swift toolchain(s) (16.4, 6.1)", run_as(self, PLATFORM_MATRIX, files, SWIFT).message)

    def test_compnerds_setup_swift_names_the_windows_toolchain(self) -> None:
        """compnerd/gha-setup-swift, the Windows Swift setup: its `swift-version`, else its `tag` (Alamofire's
        `6.3-RELEASE`), else its `branch` (`swift-6.2-release`) names the version (upstream #207)."""
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  windows:
                    runs-on: windows-latest
                    strategy:
                      matrix:
                        include:
                          - {branch: swift-6.3-release, tag: 6.3.1-RELEASE}
                          - {branch: swift-6.2-release, tag: ""}
                          - {swift: "6.1"}
                    steps:
                      - uses: compnerd/gha-setup-swift@main
                        with:
                          branch: ${{ matrix.branch }}
                          tag: ${{ matrix.tag }}
                          swift-version: ${{ matrix.swift }}
                      - run: swift test
                """
        }
        self.assertIn("3 Swift toolchain(s) (6.1, 6.2, 6.3.1)", run_as(self, PLATFORM_MATRIX, files, SWIFT).message)


class SwiftLintClaimTests(unittest.TestCase):
    PLUGIN = Setting(origin=Origin(path="Package.swift"), tool="SwiftPM", key="plugin", value="SwiftLint")

    def test_linting_runs_are_analyses(self) -> None:
        for line in ("swiftlint", "swiftlint lint", "swiftlint --strict", "swiftlint lint --quiet Sources"):
            with self.subTest(line=line):
                self.assertIsNotNone(SWIFTLINT_TOOL.claims(shell_command(line), Facts()))

    def test_fixing_runs_are_not(self) -> None:
        for line in ("swiftlint --fix", "swiftlint lint --fix", "swiftlint --autocorrect", "swiftlint autocorrect"):
            with self.subTest(line=line):
                self.assertIsNone(SWIFTLINT_TOOL.claims(shell_command(line), Facts()))

    def test_a_build_runs_it_only_with_the_plugin(self) -> None:
        self.assertIsNone(SWIFTLINT_TOOL.claims(shell_command("swift build"), Facts()))
        run = SWIFTLINT_TOOL.claims(shell_command("swift build"), Facts([self.PLUGIN]))
        self.assertIsNotNone(run)
        self.assertIsNone(SWIFTLINT_TOOL.claims(shell_command("swift package resolve"), Facts([self.PLUGIN])))
