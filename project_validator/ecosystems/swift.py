"""Swift: built with SwiftPM or Xcode, judged by the Swift and Xcode versions CI runs.

A Swift build reads its settings from Package.swift or the Xcode project, so those count as evidence of what CI builds.
"""

import re
from pathlib import PurePosixPath

from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import configuration, existing_texts, first_existing
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    BuildTypes,
    CoverageTools,
    DependencyAudit,
    DependencyManagement,
    Formatter,
    FunctionLimits,
    Hardening,
    StaticAnalysis,
    TestSuite,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, found_and_missing, matching_names, pattern

SWIFT_LANGUAGE = "Swift"
PACKAGE_SWIFT = "Package.swift"
SWIFTPM = BuildSystem(
    name="SwiftPM",
    files=(PACKAGE_SWIFT,),
    languages=frozenset({SWIFT_LANGUAGE}),
    rules=(
        BuildOutputs(
            name="the .build directory",
            globs=ignored_at_top_level(r"\.build"),
            paths=directories(".build"),
            hint="consider ignoring .build/",
            artifacts=(".build/",),
        ),
    ),
)
XCODE = BuildSystem(
    name="Xcode",
    files=("*.xcodeproj/", "*.xcworkspace/"),
    languages=frozenset({SWIFT_LANGUAGE}),
    rules=(
        BuildOutputs(
            name="Xcode's user data and derived data",
            globs=ignored_at_top_level(r"xcuserdata|DerivedData"),
            paths=directories("xcuserdata", "DerivedData"),
            hint="consider ignoring xcuserdata/ and DerivedData/",
            artifacts=("xcuserdata/", "DerivedData/"),
        ),
    ),
)
# Xcode keeps a project's build settings and its schemes inside the project directory.
XCODE_SETTINGS = re.compile(r"\.xc(?:odeproj|workspace)/(?:.+/)?(?:project\.pbxproj|[^/]+\.xcscheme)$")


def _xcode_settings(context: Context) -> list[str]:
    return [path for path in context.project.files() if XCODE_SETTINGS.search(path) or path.endswith(".xcconfig")]


def _build_texts(context: Context) -> tuple[str, ...]:
    """CI configuration, Package.swift, and the Xcode build settings and schemes."""
    return (*context.ci_texts, *existing_texts(context, (PACKAGE_SWIFT, *_xcode_settings(context))))


# swift-format and SwiftFormat have a default style; their lint modes fail only when told to.
FORMATTERS = Formatter(
    name="swift-format or SwiftFormat",
    config_file=configuration((".swift-format", ".swiftformat")),
    runs=(
        pattern("swift-format", r"\bswift(?:-|\s+)format\s+lint\b[^\n]*(?:--strict|-s)\b"),
        pattern("SwiftFormat", r"\bswiftformat\b[^\n]*--lint\b"),
    ),
    hint="consider a CI job that runs swift format lint --strict (or swiftformat --lint)",
    default_style=True,
)

TEST_CASE = re.compile(r"\bXCTestCase\b|^\s*@(?:Test|Suite)\b", re.MULTILINE)


def _swift_tests(context: Context) -> Result:
    sources = (path for path in context.project.files() if path.endswith(".swift"))
    count = sum(1 for path in sources if TEST_CASE.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no Swift tests found (XCTestCase classes or Swift Testing @Test functions)")
    return Result.passed(f"Swift tests found in {count} file(s)")


TESTS = TestSuite(
    found=_swift_tests,
    runs=(pattern("swift test", r"\bswift\s+test\b|\bxcodebuild\b[^\n]*\btest(?:-without-building)?\b"),),
    runner="swift test or xcodebuild test",
)

# Swift's coverage instrumentation counts regions (each branch of a condition is a region); llvm-cov shows no
# branches for Swift.
COVERAGE = CoverageTools(
    searched="CI configuration or the Xcode schemes",
    texts=_build_texts,
    granularity="region",
    branch=(
        pattern("swift test --enable-code-coverage", r"\bswift\s+test\b[^\n]*--enable-code-coverage\b"),
        pattern(
            "Xcode code coverage",
            r"-enableCodeCoverage\s+YES\b|\bcodeCoverageEnabled\s*=\s*\"YES\"",
        ),
    ),
)

RUNS_SWIFTLINT = r"(?<![\w-])swiftlint\b(?!\.yml)(?![^\n]*\s(?:--fix|autocorrect)\b)|\bSwiftLintPlugin\b"
SWIFTLINT = pattern("SwiftLint", RUNS_SWIFTLINT)
COMPLETE_CONCURRENCY = pattern(
    "complete concurrency checking",
    r"swift-tools-version:\s*6|\bswiftLanguageModes?\s*:\s*\[\s*\.v6|-strict-concurrency=complete"
    r"|\bStrictConcurrency\b|\bSWIFT_STRICT_CONCURRENCY\s*=\s*complete\b|\bSWIFT_VERSION\s*=\s*6",
)


def _required_warnings(_: Context) -> tuple[Pattern, ...]:
    return (SWIFTLINT, COMPLETE_CONCURRENCY)


WARNINGS = WarningPolicy(
    kind="Swift warning settings",
    recognised=(SWIFTLINT, COMPLETE_CONCURRENCY),
    required=_required_warnings,
    texts=_build_texts,
    separator=", ",
)

WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        pattern(
            "-warnings-as-errors",
            r"-warnings-as-errors\b|\btreatAllWarnings\s*\(\s*as:\s*\.error\b"
            r"|\bSWIFT_TREAT_WARNINGS_AS_ERRORS\s*=\s*YES\b",
        ),
    ),
    texts=_build_texts,
    searched="CI configuration, Package.swift or the Xcode build settings",
    hint="build with -Xswiftc -warnings-as-errors (SwiftPM 6.2: treatAllWarnings(as: .error); Xcode: "
    "SWIFT_TREAT_WARNINGS_AS_ERRORS = YES)",
)

# Compiling away Swift's bounds, overflow and exclusivity checks removes the safety the language builds in.
UNCHECKED = (
    pattern("-Ounchecked", r"-Ounchecked\b|\bSWIFT_OPTIMIZATION_LEVEL\s*=\s*\"?-Ounchecked"),
    pattern("unchecked exclusivity", r"-enforce-exclusivity=unchecked\b|\bSWIFT_ENFORCE_EXCLUSIVE_ACCESS\s*=\s*off\b"),
)


def _runtime_checks_kept(context: Context) -> Result:
    removed, _ = found_and_missing(_build_texts(context), UNCHECKED)
    if removed:
        return Result.failed(
            f"Swift's runtime safety checks are compiled away: {', '.join(removed)}",
            "build releases with -O (the default), which keeps bounds, overflow and exclusivity checks",
        )
    return Result.passed("release builds keep Swift's runtime safety checks (no -Ounchecked)")


HARDENING = Hardening(texts=_build_texts, judge=_runtime_checks_kept)

SWIFTLINT_CONFIG = ".swiftlint.yml"
FUNCTION_BODY_LENGTH_OFF = re.compile(
    r"^disabled_rules:\s*\n(?:\s+-\s*\S+\s*\n)*?\s+-\s*function_body_length\b", re.MULTILINE
)


def _function_body_length(context: Context) -> Result:
    """SwiftLint limits function length with function_body_length, on unless its configuration disables it."""
    config = first_existing(context, (SWIFTLINT_CONFIG,))
    if config is not None and FUNCTION_BODY_LENGTH_OFF.search(context.project.read_text(config)):
        return Result.failed(f"function_body_length is disabled in {config}; enable it or run {SUGGESTED_LIZARD} in CI")
    if matching_names(_build_texts(context), (SWIFTLINT,)):
        return Result.passed("function length is limited with SwiftLint function_body_length")
    return Result.failed(f"function length is never limited; run SwiftLint or {SUGGESTED_LIZARD} in CI")


STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(name="SwiftLint", runs=re.compile(RUNS_SWIFTLINT), configured=configuration((SWIFTLINT_CONFIG,))),
    ),
    texts=_build_texts,
    hint="consider running swiftlint --strict in CI (or the SwiftLint build tool plugin)",
)

# osv-scanner reads Package.resolved; Swift has no audit tool of its own.
DEPENDENCY_AUDIT = DependencyAudit(
    tools=MULTI_ECOSYSTEM_AUDITS,
    hint="consider running osv-scanner in CI, which audits the packages Package.resolved pins",
)

PACKAGE_DEPENDENCY = re.compile(r"\.package\s*\(")
EXECUTABLE = re.compile(r"\.executable(?:Target)?\s*\(")


def _declared_packages(context: Context) -> str | None:
    if context.project.exists(PACKAGE_SWIFT) and PACKAGE_DEPENDENCY.search(context.project.read_text(PACKAGE_SWIFT)):
        return "managed with SwiftPM"
    return None


def _package_resolved(context: Context) -> str | None:
    return next((path for path in context.tracked_files if PurePosixPath(path).name == "Package.resolved"), None)


def _is_application(context: Context) -> bool:
    """An app (an Xcode project, or a package with an executable) pins its packages; a library's users resolve them."""
    if any(".xcodeproj/" in path for path in context.project.files()):
        return True
    return context.project.exists(PACKAGE_SWIFT) and bool(EXECUTABLE.search(context.project.read_text(PACKAGE_SWIFT)))


DEPENDENCIES = DependencyManagement(
    managed=_declared_packages,
    locked=_package_resolved,
    lock_required=_is_application,
    lock_hint="commit Package.resolved, so the application is built with the package versions it was tested with",
)

SWIFT_TOOLCHAINS = versions_axis("Swift toolchain", SWIFT_LANGUAGE)

SWIFT = Ecosystem(
    label=SWIFT_LANGUAGE,
    languages=frozenset({SWIFT_LANGUAGE}),
    build_systems=(SWIFTPM, XCODE),
    source_suffixes={".swift": SWIFT_LANGUAGE},
    toolchain=ToolchainPatterns(
        language=SWIFT_LANGUAGE,
        versions=(
            re.compile(r"\bswift-version\W+(\d+\.\d+(?:\.\d+)?)"),
            re.compile(r"\bswift:(\d+\.\d+(?:\.\d+)?)"),
            re.compile(r"\bxcode-version\W+(\d+(?:\.\d+)*|latest(?:-stable)?)"),
            re.compile(r"\bXcode_(\d+(?:\.\d+)*)\.app\b"),
        ),
        usage=re.compile(r"\bswift\s+(?:build|test|run|package)\b|\bxcodebuild\b|\bsetup-swift\b"),
    ),
    rules=(
        SWIFT_TOOLCHAINS,
        BuildTypes(axis=SWIFT_TOOLCHAINS),
        FORMATTERS,
        COVERAGE,
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        HARDENING,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_function_body_length),
        STATIC_ANALYSIS,
        DEPENDENCIES,
    ),
)
