"""The Swift profile's rules, judged by the generic checks in the SwiftPM and Xcode project layouts."""

import unittest

from project_validator.build_configurations import detect_build_types
from project_validator.core import Result, Status
from project_validator.ecosystems import SWIFT
from project_validator.ecosystems.swift import DEPENDENCIES
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, make_context, run_as, run_in_layout, temp_project

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
        self.assertEqual(detect_build_types("swift build", "swift test -c release"), {"debug", "release"})
        self.assertEqual(detect_build_types("swift build --configuration=release"), {"release"})
        self.assertEqual(detect_build_types("xcodebuild -scheme App -configuration Debug test"), {"debug"})
        # Without -configuration, the scheme decides, which CI configuration does not show.
        self.assertEqual(detect_build_types("xcodebuild -scheme App test"), set())


class ToolTests(unittest.TestCase):
    def test_formatters_must_fail_on_findings(self) -> None:
        for command in ("swift-format lint -s -r Sources", "swift format lint --strict -r .", "swiftformat --lint ."):
            with self.subTest(command=command):
                self.assertEqual(run_as(self, CODE_FORMATTING, _ci(command), SWIFT).status, Status.PASS)
        self.assertEqual(run_as(self, CODE_FORMATTING, _ci("swift format lint -r ."), SWIFT).status, Status.FAIL)

    def test_tests_are_xctest_cases_or_swift_testing_functions(self) -> None:
        xctest = {"Tests/AppTests/AppTests.swift": "final class AppTests: XCTestCase {}\n"}
        result = run_in_layout(self, SWIFTPM, TESTS_RUN, {**xctest, **_ci("swift test")})
        self.assertEqual(result, Result.passed("Swift tests found in 1 file(s)"))
        xcode = {"AppTests/Tests.swift": "@Test func adds() {}\n", **_ci("xcodebuild -scheme App test")}
        self.assertEqual(run_in_layout(self, XCODE, TESTS_RUN, xcode).status, Status.PASS)
        self.assertEqual(run_in_layout(self, SWIFTPM, TESTS_RUN, {}).status, Status.FAIL)

    def test_coverage_counts_regions(self) -> None:
        expected = Result.passed("region coverage is reported with swift test --enable-code-coverage")
        self.assertEqual(run_in_layout(self, SWIFTPM, COVERAGE, _ci("swift test --enable-code-coverage")), expected)
        scheme = {"App.xcodeproj/xcshareddata/xcschemes/App.xcscheme": '<TestAction codeCoverageEnabled = "YES">'}
        self.assertEqual(run_in_layout(self, XCODE, COVERAGE, scheme).status, Status.PASS)
        self.assertEqual(run_in_layout(self, XCODE, COVERAGE, _ci("xcodebuild test")).status, Status.FAIL)

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
        expected = Result.passed("function length is limited with SwiftLint function_body_length")
        self.assertEqual(run_as(self, FUNCTION_LIMITS, _ci("swiftlint"), SWIFT), expected)
        disabled = {
            ".swiftlint.yml": "disabled_rules:\n  - line_length\n  - function_body_length\n",
            **_ci("swiftlint"),
        }
        self.assertEqual(run_as(self, FUNCTION_LIMITS, disabled, SWIFT).status, Status.FAIL)
        self.assertEqual(run_as(self, FUNCTION_LIMITS, {}, SWIFT).status, Status.FAIL)


class DependencyAndOutputTests(unittest.TestCase):
    PACKAGE = '.package(url: "https://github.com/apple/swift-log", from: "1.6.0")'

    def test_an_application_commits_package_resolved(self) -> None:
        app = {"Package.swift": f'dependencies: [{self.PACKAGE}], targets: [.executableTarget(name: "App")]\n'}
        expected = Result.warned("dependencies are managed with SwiftPM but not locked", DEPENDENCIES.lock_hint)
        self.assertEqual(run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, app), expected)
        locked = run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, {**app, "Package.resolved": "{}"})
        self.assertEqual(locked.message, "dependencies are managed with SwiftPM and locked in Package.resolved")

    def test_a_library_need_not(self) -> None:
        library = {"Package.swift": f'dependencies: [{self.PACKAGE}], targets: [.target(name: "Lib")]\n'}
        self.assertEqual(
            run_in_layout(self, SWIFTPM, DEPENDENCY_MANAGEMENT, library),
            Result.passed("dependencies are managed with SwiftPM"),
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
