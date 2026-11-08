""".NET's tools: what runs its tests, measures coverage, formats, analyses, scans and audits, and the
settings each reads (see `project_validator.facts.tools`)."""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.ecosystems.dotnet import (
    CSHARP,
    DOTNET_LANGUAGES,
    FSHARP,
    SETTINGS_FILES,
    builds_project,
    msbuild_property,
)
from project_validator.facts import Command, Facts, Setting, Unknown, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings, settings, xml_root
from project_validator.facts.testing import TestFile, TestFiles, test_runner, tested
from project_validator.facts.tools import Definition, Run, defined_by, starts
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

EDITORCONFIG_FILES = file_reader("EditorConfig", (".editorconfig",))


CSHARPIER_FILES = file_reader("CSharpier", (".csharpierrc", ".csharpierrc.json", ".csharpierrc.yaml"))


# Each of them has a default style: dotnet format reads .editorconfig, and CSharpier and Fantomas have their own.
DOTNET_FORMAT = format_tool(
    name="dotnet format",
    languages=frozenset({CSHARP}),
    can={Enforcement.CHECK: "dotnet format --verify-no-changes", Enforcement.APPLY: "dotnet format"},
    formats=flagged(("dotnet", "format"), checks=("--verify-no-changes",)),
    style=defined_by(files=("EditorConfig",)),
)


CSHARPIER = format_tool(
    name="CSharpier",
    languages=frozenset({CSHARP}),
    can={Enforcement.CHECK: "csharpier check .", Enforcement.APPLY: "csharpier format ."},
    formats=flagged(("csharpier",), ("dotnet", "csharpier"), checks=("check", "--check")),
    style=defined_by(files=("CSharpier",)),
)


FANTOMAS = format_tool(
    name="Fantomas",
    languages=frozenset({FSHARP}),
    can={Enforcement.CHECK: "fantomas --check .", Enforcement.APPLY: "fantomas ."},
    formats=flagged(("fantomas",), ("dotnet", "fantomas"), checks=("--check",)),
    style=defined_by(files=("EditorConfig",)),
)


# xUnit, NUnit and MSTest, in C# ([Fact]) and F# ([<Fact>]).
DOTNET_TEST_FILES = TestFiles(
    name="[Fact], [Test] or [TestMethod] methods in a test project (one referencing Microsoft.NET.Test.Sdk)",
    languages=DOTNET_LANGUAGES,
    path=re.compile(r"\.(?:cs|fs)$"),
    contains=re.compile(r"\[<?\s*(?:Fact|Theory|Test|TestCase|TestMethod|DataTestMethod)\b"),
)


def _test_project(facts: Facts) -> bool:
    """Whether a project references the test SDK (Microsoft.NET.Test.Sdk, or MSTest's own SDK)."""
    settings_ = facts.settings("MSBuild")
    return any(
        (found.key == "PackageReference" and str(found.value) == "Microsoft.NET.Test.Sdk")
        or (found.key == "Sdk" and str(found.value).startswith("MSTest.Sdk"))
        for found in settings_
    )


def _dotnet_tests(facts: Facts) -> Iterator[str]:
    """The test files, when a test project runs them."""
    if _test_project(facts):
        yield from (test.origin.path for test in facts.of(TestFile) if test.kind == DOTNET_TEST_FILES.name)


DOTNET_TEST = test_runner(
    name="dotnet test",
    languages=DOTNET_LANGUAGES,
    how="dotnet test",
    runs=lambda command, _facts: tested() if resolved(command)[:2] == ("dotnet", "test") else None,
    tests=Definition(found=_dotnet_tests, default=False, describe=DOTNET_TEST_FILES.name, from_test_units=True),
    reads=("MSBuild",),
)


# coverlet and Microsoft's code coverage (dotnet-coverage, Microsoft.Testing.Platform) both count branches.
_COLLECT_COVERAGE = re.compile(msbuild_property("CollectCoverage", "true"), re.IGNORECASE)


_ELEMENT = re.compile(r"<(\w+)>\s*([^<]*?)\s*</\1>")


_REFERENCE = re.compile(r"""<(?:Global)?PackageReference\s+(?:Include|Update)\s*=\s*["']([^"']+)""")


_FRIENDLY_NAME = re.compile(r"""friendlyName\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _read_msbuild_properties(path: str, text: str) -> Iterator[Setting]:
    """The properties a project file or shared MSBuild file sets, and the packages it references; matched in its
    text when it does not parse."""
    root = xml_root("MSBuild", path, text)
    if isinstance(root, Unknown):
        found = ((match[1], match[2]) for match in _ELEMENT.finditer(text))
        yield from settings("MSBuild", path, found, heuristic=True)
        yield from matched_settings("MSBuild", path, text, {"PackageReference": (_REFERENCE, None)})
        return
    properties = ((child.tag, (child.text or "").strip()) for group in root.iter("PropertyGroup") for child in group)
    yield from settings("MSBuild", path, properties)
    references = (
        reference.get("Include") or reference.get("Update") or ""
        for kind in ("PackageReference", "GlobalPackageReference")
        for reference in root.iter(kind)
    )
    yield from settings("MSBuild", path, (("PackageReference", name) for name in references if name))
    if sdk := root.get("Sdk"):
        yield from settings("MSBuild", path, (("Sdk", sdk),))


def _read_run_settings(path: str, text: str) -> Iterator[Setting]:
    """The data collectors a .runsettings file adds, by friendly name."""
    root = xml_root("VSTest", path, text)
    if isinstance(root, Unknown):
        yield from matched_settings("VSTest", path, text, {"DataCollector": (_FRIENDLY_NAME, None)})
        return
    names = (collector.get("friendlyName", "") for collector in root.iter("DataCollector"))
    yield from settings("VSTest", path, (("DataCollector", name) for name in names))


def _dotnet_test(command: Command) -> tuple[str, ...] | None:
    argv = resolved(command)
    return argv if starts_with(argv, ("dotnet", "test")) else None


def _named_run_settings(command: Command) -> list[str]:
    argv = _dotnet_test(command) or ()
    return [joined(command.directory, path) for path in option_values(argv, "--settings", "-s")]


MSBUILD_PROPERTIES = SettingsReader(name="MSBuild", files=SETTINGS_FILES, read=_read_msbuild_properties)


RUN_SETTINGS = SettingsReader(
    name="VSTest", files=("*.runsettings",), read=_read_run_settings, named_by=_named_run_settings
)


def _relative(setting: Setting) -> str:
    """A path a setting names, relative to the project (MSBuild paths are relative to the file that sets them)."""
    directory = str(PurePosixPath(setting.path).parent)
    return joined(directory, str(setting.value).replace("\\", "/").removeprefix("./"))


def _coverlet(command: Command, facts: Facts) -> Run | None:
    """coverlet: its data collector (`--collect "XPlat Code Coverage"`, or a .runsettings that adds it), its MSBuild
    integration (`CollectCoverage=true` on the command line or in the project settings), or its console tool."""
    if starts_with(resolved(command), ("coverlet",)):
        return measured(Granularity.LINE, Granularity.BRANCH)
    if (argv := _dotnet_test(command)) is None:
        return None
    collectors = [*option_values(argv, "--collect"), *(word[10:] for word in argv if word.startswith("--collect:"))]
    if any(collector.strip("\"'").lower() == "xplat code coverage" for collector in collectors):
        return measured(Granularity.LINE, Granularity.BRANCH)
    if _COLLECT_COVERAGE.search(" ".join(argv)):
        return measured(Granularity.LINE, Granularity.BRANCH)
    read = [
        setting
        for setting in facts.where(Setting, tool="MSBuild", key="CollectCoverage")
        if str(setting.value).lower() == "true"
    ]
    named = [_relative(setting) for setting in facts.where(Setting, tool="MSBuild", key="RunSettingsFilePath")]
    read += [
        setting
        for setting in facts.settings("VSTest", paths=[*_named_run_settings(command), *named])
        if str(setting.value).lower() == "xplat code coverage"
    ]
    return measured(Granularity.LINE, Granularity.BRANCH, read=read) if read else None


def _microsoft_coverage(command: Command, _: Facts) -> Run | None:
    """Microsoft code coverage: `dotnet-coverage collect`, or Microsoft.Testing.Platform's `dotnet test --coverage`."""
    argv = resolved(command)
    collects = starts_with(argv, ("dotnet-coverage", "collect")) is not None
    if collects or (_dotnet_test(command) is not None and "--coverage" in argv):
        return measured(Granularity.LINE, Granularity.BRANCH)
    return None


COVERLET = coverage_tool(
    name="coverlet",
    languages=DOTNET_LANGUAGES,
    can={
        Granularity.LINE: 'dotnet test --collect "XPlat Code Coverage"',
        Granularity.BRANCH: 'dotnet test --collect "XPlat Code Coverage"',
    },
    measures=_coverlet,
    reads=("MSBuild", "VSTest"),
)


MICROSOFT_CODE_COVERAGE = coverage_tool(
    name="Microsoft code coverage",
    languages=DOTNET_LANGUAGES,
    can={Granularity.LINE: "dotnet-coverage collect", Granularity.BRANCH: "dotnet-coverage collect"},
    measures=_microsoft_coverage,
)


# The commands that restore a project's packages, which NuGet audits as it restores them.
_RESTORES = frozenset({"restore", "build", "test", "pack", "publish", "run"})


def _nuget_audit(command: Command, facts: Facts) -> Run | None:
    """Restoring with `<NuGetAuditMode>all</NuGetAuditMode>`, which audits the transitive packages too."""
    argv = resolved(command)
    restores = starts_with(argv, ("msbuild",), ("MSBuild",), *(("dotnet", restore) for restore in _RESTORES))
    read = [
        found
        for found in facts.where(Setting, tool="MSBuild", key="NuGetAuditMode")
        if str(found.value).lower() == "all"
    ]
    return audited(read=read) if restores and read else None


def _list_vulnerable(command: Command, _facts: Facts) -> Run | None:
    argv = resolved(command)
    listing = starts(("dotnet", "list"), ("dotnet", "package", "list"))(command) and "package" in argv[1:4]
    return audited() if listing and "--vulnerable" in argv else None


AUDITORS = (
    auditor(
        name="NuGet audit of every package",
        languages=DOTNET_LANGUAGES,
        how="a restore with <NuGetAuditMode>all</NuGetAuditMode>",
        audits=_nuget_audit,
        reads=("MSBuild",),
    ),
    auditor(
        name="dotnet list package --vulnerable",
        languages=DOTNET_LANGUAGES,
        how="dotnet list package --vulnerable --include-transitive",
        audits=_list_vulnerable,
    ),
    *multi_ecosystem_audits(DOTNET_LANGUAGES),
)


ANALYZER_CONFIGURATION = (".editorconfig", ".globalconfig")


_SECURITY_SEVERITY = re.compile(r"\bdotnet_analyzer_diagnostic\.category-Security\.severity\s*=\s*(warning|error)\b")


ANALYZER_SETTINGS = SettingsReader(
    name="analyzer configuration",
    files=ANALYZER_CONFIGURATION,
    read=lambda path, text: matched_settings("MSBuild", path, text, {"SecuritySeverity": (_SECURITY_SEVERITY, None)}),
)


_SECURE = frozenset({"recommended", "all", "warning", "error"})


def _security_analysis(command: Command, facts: Facts) -> Run | None:
    """A build with the SDK's security analyzers turned up (`AnalysisModeSecurity`, or the Security category's
    severity in .editorconfig), or with Security Code Scan's package referenced."""
    if not builds_project(command):
        return None
    read = [
        found
        for found in facts.settings("MSBuild")
        if (found.key in ("AnalysisModeSecurity", "SecuritySeverity") and str(found.value).lower() in _SECURE)
        or (found.key == "PackageReference" and str(found.value).startswith("SecurityCodeScan"))
    ]
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(
        name=".NET security analyzers",
        languages=DOTNET_LANGUAGES,
        how="<AnalysisModeSecurity>Recommended</AnalysisModeSecurity> (or Security Code Scan)",
        scans=_security_analysis,
        reads=("MSBuild", "analyzer configuration"),
    ),
    *multi_language_scanners(DOTNET_LANGUAGES),
)


# lizard measures C# but not F#, and no F# tool is known to limit function length.
FUNCTION_LENGTH_LIMITERS = function_length_limiters(frozenset({CSHARP}))


FSHARPLINT = analyzer(
    name="FSharpLint",
    languages=frozenset({FSHARP}),
    how="dotnet fsharplint lint",
    analyses=lambda command, _facts: (
        analysed() if command.argv[:2] in (("fsharplint", "lint"), ("dotnet", "fsharplint")) else None
    ),
)
