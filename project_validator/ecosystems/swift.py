"""Swift: built with SwiftPM or Xcode, judged by the Swift and Xcode versions CI runs.

A Swift build reads its settings from Package.swift or the Xcode project, so those count as evidence of what CI builds.
"""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.build_configurations import build_type_kinds
from project_validator.core import Context, Result
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import configuration, existing_texts, first_existing
from project_validator.facts import Command, Fact, Facts, Setting, Unknown, resolved
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.settings import SettingsReader, json_settings, settings, xml_root
from project_validator.facts.tools import Run
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    BuildTypes,
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


def swiftpm_build_types(command: Command) -> frozenset[str]:
    """The configuration `swift build`, `test` or `run` builds: `-c` / `--configuration`, or SwiftPM's default
    (debug)."""
    argv = resolved(command)
    if argv[:1] != ("swift",) or len(argv) < 2 or argv[1] not in ("build", "test", "run"):
        return frozenset()
    return build_type_kinds(*(option_values(argv, "-c", "--configuration") or ["debug"]))


def xcode_build_types(command: Command) -> frozenset[str]:
    """The configuration xcodebuild builds, when it names one; without `-configuration`, the scheme decides."""
    argv = resolved(command)
    return build_type_kinds(*option_values(argv, "-configuration")) if argv[:1] == ("xcodebuild",) else frozenset()


SWIFTPM = BuildSystem(
    name="SwiftPM",
    files=(PACKAGE_SWIFT,),
    languages=frozenset({SWIFT_LANGUAGE}),
    build_types=swiftpm_build_types,
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
    build_types=xcode_build_types,
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


def _swift_test(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) != "swift" or argv[1:2] != ("test",) or not has_option(argv, "--enable-code-coverage"):
        return None
    return measured(Granularity.LINE, Granularity.REGION)


def _read_xcode_settings(path: str, text: str) -> Iterator[Fact]:
    """A scheme's test action attributes, or a test plan's options."""
    if path.endswith(".xctestplan"):
        yield from json_settings("Xcode", path, text)
        return
    root = xml_root("Xcode", path, text)
    if isinstance(root, Unknown):
        yield root
        return
    for action in root.iter("TestAction"):
        yield from settings("Xcode", path, ((f"TestAction.{name}", value) for name, value in action.attrib.items()))


XCODE_TEST_SETTINGS = SettingsReader(name="Xcode", files=("*.xcscheme", "*.xctestplan"), read=_read_xcode_settings)


def _turns_on_coverage(setting: Setting) -> bool:
    if setting.key == "TestAction.codeCoverageEnabled":
        return setting.value == "YES"
    return setting.key.startswith("defaultOptions.codeCoverage") and setting.value is not False


def _xcodebuild(command: Command, facts: Facts) -> Run | None:
    """`xcodebuild test`, with code coverage turned on by its options, the scheme it runs or a test plan (any scheme
    when it names none)."""
    argv = resolved(command)
    if program(argv) != "xcodebuild" or not {"test", "test-without-building"} & set(argv):
        return None
    if "YES" in option_values(argv, "-enableCodeCoverage"):
        return measured(Granularity.LINE, Granularity.REGION)
    schemes = tuple(f"/{name}.xcscheme" for name in option_values(argv, "-scheme")) or (".xcscheme",)
    read = [
        setting
        for setting in facts.settings("Xcode")
        if setting.path.endswith((*schemes, ".xctestplan")) and _turns_on_coverage(setting)
    ]
    return measured(Granularity.LINE, Granularity.REGION, read=read) if read else None


SWIFT_ONLY = frozenset({SWIFT_LANGUAGE})
SWIFTPM_COVERAGE = coverage_tool(
    name="swift test",
    languages=SWIFT_ONLY,
    can={
        Granularity.LINE: "swift test --enable-code-coverage",
        Granularity.REGION: "swift test --enable-code-coverage",
    },
    measures=_swift_test,
)
XCODE_COVERAGE = coverage_tool(
    name="Xcode",
    languages=SWIFT_ONLY,
    can={
        Granularity.LINE: "xcodebuild test -enableCodeCoverage YES",
        Granularity.REGION: "xcodebuild test -enableCodeCoverage YES",
    },
    measures=_xcodebuild,
    reads=("Xcode",),
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
