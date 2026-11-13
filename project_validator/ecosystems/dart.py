"""Dart and Flutter: built with pub (`pubspec.yaml`), judged by the Dart or Flutter SDK versions CI runs and by the
`dart` and `flutter` commands it runs. Flutter is Dart with a framework: `flutter test`, `flutter analyze` and the
Flutter SDK count wherever their Dart counterparts do."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from project_validator import yaml_support
from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, program, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.formatting import Enforcement, format_tool, formatted
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Condition, Run, defined_by, starts, when
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

DART = frozenset({"Dart"})
PUBSPEC = "pubspec.yaml"
ANALYSIS_OPTIONS = "analysis_options.yaml"


def _pubspec(text: str) -> Mapping[str, object]:
    """A pubspec as a mapping; one that does not parse is a ValueError, which makes the manifest unknown."""
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        raise ValueError(str(error)) from error
    return document if isinstance(document, Mapping) else {}


def _workspace_members(text: str) -> tuple[str, ...]:
    """The packages of a pub workspace (`workspace:` in the root pubspec, Dart 3.6), each a unit of its own."""
    try:
        members = _pubspec(text).get("workspace")
    except ValueError:
        return ()
    return tuple(str(member) for member in members) if isinstance(members, list) else ()


def _build_beside_pubspec(directory: Path) -> bool:
    return directory.name == "build" and (directory.parent / PUBSPEC).is_file()


PUB = BuildSystem(
    name="pub", files=(PUBSPEC,), languages=DART, members=_workspace_members, is_build_tree=_build_beside_pubspec
)


def _dart(*subcommands: str) -> Condition:
    """Whether a command is `dart <subcommand>` or `flutter <subcommand>` (or `dart run <subcommand>`, which runs the
    package of that name: `dart run test`)."""
    prefixes = tuple((tool, subcommand) for tool in ("dart", "flutter") for subcommand in subcommands)
    return starts(*prefixes, *(("dart", "run", subcommand) for subcommand in subcommands))


# --- Tests and coverage -------------------------------------------------------------------------------------------

DART_TEST_FILES = TestFiles(
    name="test(), testWidgets() or group() calls in test/**/*_test.dart",
    languages=DART,
    path=re.compile(r"(?:^|/)test/.+_test\.dart$"),
    contains=re.compile(r"\b(?:test|testWidgets|testGoldens|group)\s*\("),
)

_RUNS_TESTS = starts(("dart", "test"), ("flutter", "test"), ("dart", "run", "test"), ("very_good", "test"))

DART_TEST = test_runner(
    name="dart test",
    languages=DART,
    how="dart test (or flutter test)",
    runs=when(_RUNS_TESTS, tested),
    tests=tests_of(DART_TEST_FILES.name),
)


def _test_coverage(command: Command, _facts: Facts) -> Run | None:
    """`dart test --coverage=<dir>` and `flutter test --coverage` write line coverage; with `--branch-coverage` (Dart
    2.17+), branches too. `dart run coverage:test_with_coverage` is the same collection by package:coverage."""
    argv = resolved(command)
    collects = starts_with(argv, ("dart", "run", "coverage:test_with_coverage"), ("very_good", "test"))
    if collects is None and not (_RUNS_TESTS(command) and has_option(argv, "--coverage")):
        return None
    if collects is not None and program(argv) == "very_good" and not has_option(argv, "--coverage"):
        return None
    branches = Granularity.BRANCH if has_option(argv, "--branch-coverage") else None
    return measured(Granularity.LINE, branches)


DART_COVERAGE = coverage_tool(
    name="dart test --coverage",
    languages=DART,
    can={
        Granularity.LINE: "dart test --coverage=coverage (or flutter test --coverage)",
        Granularity.BRANCH: "dart test --coverage=coverage --branch-coverage (or flutter test --coverage "
        "--branch-coverage)",
    },
    measures=_test_coverage,
)


# --- Formatting ---------------------------------------------------------------------------------------------------


def _dart_format(command: Command, facts: Facts) -> Run | None:
    """`dart format --set-exit-if-changed` fails on a file it would change (with `--output=none`, without writing);
    `--output=none` alone only lists, and plain `dart format` rewrites."""
    argv = resolved(command)
    if starts_with(argv, ("dart", "format")) is None:
        return None
    if has_option(argv, "--set-exit-if-changed"):
        return formatted(command, facts, checks=True)
    if has_option(argv, "--output", "-o") and any(word in ("none", "show", "json") for word in argv[2:]):
        return None
    return formatted(command, facts, checks=False)


# dart format has one style (and a page width, set in analysis_options.yaml since Dart 3.7).
DART_FORMAT = format_tool(
    name="dart format",
    languages=DART,
    can={Enforcement.CHECK: "dart format --output=none --set-exit-if-changed .", Enforcement.APPLY: "dart format ."},
    formats=_dart_format,
    style=defined_by(),
)


# --- Warnings and analysis ------------------------------------------------------------------------------------------


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


# The analyzer reports what other compilers warn about; a lint set turns on the lints worth the name.
LINT_SET = _setting(
    "a lint set in analysis_options.yaml",
    r"^include:\s*package:(?:lints/recommended|flutter_lints/flutter|very_good_analysis/analysis_options"
    r"|lint/(?:strict|analysis_options|package)|pedantic/analysis_options)",
)
ANALYZE = _setting("dart analyze", r"\b(?:dart|flutter)\s+analyze\b")
# `dart analyze` fails on warnings already; `--fatal-infos` makes the infos (the lints' level) fatal too.
FATAL_INFOS = _setting("--fatal-infos", r"\b(?:dart|flutter)\s+analyze\b[^\n]*\s--fatal-infos\b")

ANALYSIS_OPTIONS_READER = requirement_reader("Dart analysis options", (ANALYSIS_OPTIONS,), (required(LINT_SET),))

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=DART,
    requirements=always(required(LINT_SET), required(ANALYZE, in_files=False)),
    reads=(ANALYSIS_OPTIONS_READER.name,),
    words=Wording(
        kind="Dart analyzer settings",
        hint="include package:lints/recommended.yaml (or flutter_lints, very_good_analysis) in analysis_options.yaml "
        "and run dart analyze in CI",
        searched="analysis_options.yaml and CI configuration",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=DART,
    requirements=always(required(FATAL_INFOS, in_files=False)),
    words=Wording(kind="warnings as errors", hint="run dart analyze --fatal-infos in CI"),
)

DART_ANALYZE = analyzer(
    name="dart analyze",
    languages=DART,
    how="dart analyze (or flutter analyze)",
    analyses=when(_dart("analyze"), analysed),
    rules=defined_by(files=(ANALYSIS_OPTIONS_READER.name,)),
)
CUSTOM_LINT = analyzer(
    name="custom_lint",
    languages=DART,
    how="dart run custom_lint",
    analyses=when(starts(("dart", "run", "custom_lint"), ("flutter", "pub", "run", "custom_lint")), analysed),
)
DCM = analyzer(name="DCM", languages=DART, how="dcm analyze lib", analyses=when(starts(("dcm", "analyze")), analysed))

# semgrep reads Dart; CodeQL and GitLab SAST do not.
SECURITY_SCANNERS = multi_language_scanners(DART)
# osv-scanner and trivy read pubspec.lock; snyk and GitLab Dependency Scanning do not.
AUDITORS = multi_ecosystem_audits(DART)

FUNCTION_LENGTH_LIMITERS = function_length_limiters(DART)


# --- Dependencies and outputs -------------------------------------------------------------------------------------


def _declares(_path: str, text: str) -> bool:
    pubspec = _pubspec(text)
    return any(isinstance(pubspec.get(key), Mapping) and pubspec[key] for key in ("dependencies", "dev_dependencies"))


def _publishable(text: str) -> bool:
    return str(_pubspec(text).get("publish_to", "")).strip("'\"") != "none"


# pub's guidance: an application commits pubspec.lock, a package that may be published does not.
PUBSPEC_DEPENDENCIES = manifest_reader(
    name="pubspec dependencies",
    manager="pub",
    files=(PUBSPEC,),
    declares=_declares,
    application=lambda _path, text: not _publishable(text),
    library=lambda _path, text: _publishable(text),
)
PUBSPEC_LOCK = lockfile_reader(manager="pub", files=("pubspec.lock",))
PUB_PACKAGES = PackageManager(
    name="pub",
    languages=DART,
    lock=Lock.APPLICATIONS,
    lock_hint="commit pubspec.lock (an application, with publish_to: none; a package that may be published leaves it "
    "out)",
)

DART_TOOL = BuildOutput(
    languages=DART,
    name="the .dart_tool directory",
    globs=ignored_at_top_level(r"\.dart_tool"),
    paths=directories(".dart_tool"),
    hint="consider ignoring .dart_tool/ (and build/ and coverage/)",
    artifacts=(".dart_tool/", "build/"),
)


# --- Recognition and toolchains -----------------------------------------------------------------------------------

_SDK = r"(\d+\.\d+(?:\.\d+)?|stable|beta|dev|main)"
_FLUTTER = r"(\d+\.\d+(?:\.\d+)?)"

# dart-lang/setup-dart's `sdk` (a version or a channel) and the `dart` image name Dart SDKs; subosito/flutter-action's
# `flutter-version` and the cirruslabs image name Flutter SDKs, each of which brings its Dart.
_SDK_VERSIONS = (
    (re.compile(rf"\bsdk:\s*[\"']?{_SDK}\b"), "Dart {}"),
    (re.compile(rf"\bdart:{_SDK}\b"), "Dart {}"),
    (re.compile(rf"\bflutter-version:\s*[\"']?{_FLUTTER}"), "Flutter {}"),
    (re.compile(rf"\bcirruslabs/flutter:{_FLUTTER}"), "Flutter {}"),
)

DART_ECOSYSTEM = Ecosystem(
    label="Dart",
    languages=DART,
    build_systems=(PUB,),
    source_suffixes={".dart": "Dart"},
    toolchain=toolchain_patterns(
        "Dart",
        programs=(
            *subcommands("dart", "test", "analyze", "format", "pub", "run", "compile", "fix", "doc"),
            *subcommands("flutter", "test", "analyze", "pub", "build", "run", "doc", "gen-l10n"),
            ("very_good", "test"),
        ),
        actions=("flutter-action",),
        setup=("dart",),
        labelled=_SDK_VERSIONS,
    ),
)

DART_VERSIONS = versions_axis("Dart or Flutter SDK version", "Dart", DART)
