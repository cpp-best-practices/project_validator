""".NET (C# and F#): built with MSBuild and the dotnet CLI, judged by the .NET SDK versions CI runs.

A .NET build reads its settings (analyzers, warnings, coverage, auditing) from the project files and
Directory.Build.props, so those count as CI configuration when CI builds the project.
"""

import re
from collections.abc import Callable, Iterator
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from project_validator.core import Context, Result, Status
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, existing_texts
from project_validator.facts import Command, Facts, Setting, Unknown, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, program
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import joined
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings, settings, xml_root
from project_validator.facts.tools import Claim, Definition, Run, defined_by
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    BuildOutputs,
    DeclaredLicense,
    DependencyAudit,
    DependencyManagement,
    FunctionLimits,
    SecurityLints,
    TestSuite,
    WarningPolicy,
    WarningsAsErrors,
    directories,
    ignored_at_top_level,
)
from project_validator.text import Pattern, pattern

CSHARP = "C#"
FSHARP = "F#"
PROJECT_FILES = ("*.csproj", "*.fsproj")
# MSBuild reads these beside (or above) every project.
SHARED_SETTINGS = ("Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props")
SETTINGS_FILES = (*PROJECT_FILES, *SHARED_SETTINGS)


def _is_build_output(directory: Path) -> bool:
    """`bin/` and `obj/` beside a project file hold its build output."""
    if directory.name not in {"bin", "obj"}:
        return False
    return any(fnmatchcase(entry.name, glob) for entry in directory.parent.iterdir() for glob in PROJECT_FILES)


MSBUILD = BuildSystem(
    name="MSBuild",
    files=(*PROJECT_FILES, "*.sln", "*.slnx", *SHARED_SETTINGS, "global.json"),
    is_build_tree=_is_build_output,
)

RUNS_BUILD = re.compile(r"\bdotnet\s+(?:build|test|publish|pack|run|restore)\b")


def _settings_files(context: Context) -> list[str]:
    """The project files and shared MSBuild settings, in every directory."""
    files = context.project.files()
    return [path for path in files if any(fnmatchcase(PurePosixPath(path).name, glob) for glob in SETTINGS_FILES)]


def _build_texts(context: Context) -> tuple[str, ...]:
    """CI configuration and pre-commit hooks, with the project files and shared MSBuild settings when CI builds."""
    texts = ci_and_hook_texts(context)
    if not any(map(RUNS_BUILD.search, texts)):
        return texts
    return (*texts, *(context.project.read_text(path) for path in _settings_files(context)))


def _with_files(*files: str) -> Callable[[Context], tuple[str, ...]]:
    def texts(context: Context) -> tuple[str, ...]:
        return (*_build_texts(context), *existing_texts(context, files))

    return texts


def _property(name: str, values: str) -> str:
    """An MSBuild property set to one of `values`, in a project file or on the command line."""
    return rf"<{name}>\s*(?:{values})\s*</{name}>|[-/]p(?:roperty)?:{name}=(?:{values})\b"


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

TEST_SDK = re.compile(r"\bMicrosoft\.NET\.Test\.Sdk\b|\bSdk\s*=\s*[\"']MSTest\.Sdk\b")
# xUnit, NUnit and MSTest, in C# ([Fact]) and F# ([<Fact>]).
TEST_ATTRIBUTE = re.compile(r"\[<?\s*(?:Fact|Theory|Test|TestCase|TestMethod|DataTestMethod)\b")
SOURCE_SUFFIXES = (".cs", ".fs")


def _dotnet_tests(context: Context) -> Result:
    projects = [path for path in _settings_files(context) if path.endswith(("proj", ".props"))]
    if not any(TEST_SDK.search(context.project.read_text(path)) for path in projects):
        return Result.failed("no .NET test project found (one referencing Microsoft.NET.Test.Sdk)")
    sources = (path for path in context.project.files() if path.endswith(SOURCE_SUFFIXES))
    count = sum(1 for path in sources if TEST_ATTRIBUTE.search(context.project.read_text(path)))
    if count == 0:
        return Result.failed("no .NET tests found ([Fact], [Test] or [TestMethod] methods)")
    return Result.passed(f".NET tests found in {count} file(s)")


TESTS = TestSuite(found=_dotnet_tests, runs=(pattern("dotnet test", r"\bdotnet\s+test\b"),), runner="dotnet test")

# coverlet and Microsoft's code coverage (dotnet-coverage, Microsoft.Testing.Platform) both count branches.
_COLLECT_COVERAGE = re.compile(_property("CollectCoverage", "true"), re.IGNORECASE)
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
    return argv if program(argv) == "dotnet" and argv[1:2] == ("test",) else None


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
    if program(resolved(command)) == "coverlet":
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
    collects = program(argv) == "dotnet-coverage" and argv[1:2] == ("collect",)
    if collects or (_dotnet_test(command) is not None and "--coverage" in argv):
        return measured(Granularity.LINE, Granularity.BRANCH)
    return None


DOTNET_LANGUAGES = frozenset({CSHARP, FSHARP})
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

ANALYSIS_MODE = Pattern(
    "AnalysisMode Recommended or All",
    re.compile(
        r"<AnalysisMode>\s*(?:Recommended|All)\s*</AnalysisMode>"
        r"|<AnalysisLevel>\s*[\w.]*-?(?:recommended|all)\s*</AnalysisLevel>",
        re.IGNORECASE,
    ),
)
ENFORCE_CODE_STYLE = Pattern("EnforceCodeStyleInBuild", re.compile(_property("EnforceCodeStyleInBuild", "true"), re.I))
NULLABLE = Pattern("Nullable enable", re.compile(_property("Nullable", "enable"), re.IGNORECASE))
# The .NET analyzers do not analyze F#; its compiler has warnings to turn on.
FSHARP_WARNINGS = Pattern("F# --warnon", re.compile(r"<WarnOn>[^<]+</WarnOn>|--warnon:\S+", re.IGNORECASE))


def _required_settings(context: Context) -> tuple[Pattern, ...]:
    if CSHARP in context.structure.languages:
        return (ANALYSIS_MODE, ENFORCE_CODE_STYLE, NULLABLE)
    return (FSHARP_WARNINGS,)


WARNINGS = WarningPolicy(
    kind=".NET analyzer settings",
    recognised=(ANALYSIS_MODE, ENFORCE_CODE_STYLE, NULLABLE, FSHARP_WARNINGS),
    required=_required_settings,
    texts=_build_texts,
    separator=", ",
)

WARNINGS_AS_ERRORS = WarningsAsErrors(
    flags=(
        pattern(
            "TreatWarningsAsErrors",
            rf"{_property('TreatWarningsAsErrors', 'true')}|(?<![\w-])[-/]{{1,2}}warnaserror(?![\w:-])",
        ),
    ),
    texts=_build_texts,
    searched="the MSBuild settings CI builds with, or CI configuration",
    hint="set <TreatWarningsAsErrors>true</TreatWarningsAsErrors> in Directory.Build.props",
)

DEPENDENCY_AUDIT = DependencyAudit(
    tools=(
        pattern("NuGet audit of every package", r"<NuGetAuditMode>\s*all\s*</NuGetAuditMode>"),
        pattern(
            "dotnet list package --vulnerable",
            r"\bdotnet\s+(?:list\s+(?:\S+\s+)?package|package\s+list)\b[^\n]*--vulnerable\b",
        ),
        *MULTI_ECOSYSTEM_AUDITS,
    ),
    hint="set <NuGetAuditMode>all</NuGetAuditMode>, so restoring audits transitive packages too, or run "
    "dotnet list package --vulnerable --include-transitive in CI",
    texts=_build_texts,
)

ANALYZER_CONFIGURATION = (".editorconfig", ".globalconfig")

SECURITY_LINTS = SecurityLints(
    texts=_with_files(*ANALYZER_CONFIGURATION),
    lints=(
        pattern(
            ".NET security analyzers",
            r"<AnalysisModeSecurity>\s*(?:Recommended|All)\s*</AnalysisModeSecurity>"
            r"|\bdotnet_analyzer_diagnostic\.category-Security\.severity\s*=\s*(?:warning|error)\b",
        ),
        pattern("Security Code Scan", r"\bSecurityCodeScan\b"),
    ),
)


def _fsharp_only(context: Context) -> Result:
    """lizard measures C# but not F#, and no F# tool is known to limit function length."""
    if CSHARP in context.structure.languages:
        return Result.failed(f"function length is never limited; run {SUGGESTED_LIZARD} in CI")
    return Result(status=Status.SKIP, message="no known tool limits the length of F# functions")


# The commands that build a project, and so run the analyzers its packages add.
_BUILDS = frozenset({"build", "test", "pack", "publish", "run", "msbuild"})


def _analyzer_package(prefix: str) -> Claim:
    """An analyzer a NuGet package adds to the compiler, which runs on every build of a project that references it."""

    def analyses(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        builds = program(argv) in ("msbuild", "MSBuild") or (
            program(argv) == "dotnet" and argv[1:2] and argv[1] in _BUILDS
        )
        references = facts.where(Setting, tool="MSBuild", key="PackageReference")
        read = [found for found in references if str(found.value).lower().startswith(prefix.lower())]
        return analysed(read=read) if builds and read else None

    return analyses


def _analyzer_definition(prefix: str) -> Definition:
    def found(facts: Facts) -> Iterator[str]:
        references = facts.where(Setting, tool="MSBuild", key="PackageReference")
        return (found.path for found in references if str(found.value).lower().startswith(prefix.lower()))

    return Definition(found=found)


# The SDK's own analyzers are judged by compiler-warnings; static analysis asks for a package beyond them.
DOTNET_ANALYZERS = tuple(
    analyzer(
        name=name,
        languages=frozenset({CSHARP}),
        how=name,
        analyses=_analyzer_package(prefix),
        rules=_analyzer_definition(prefix),
        reads=("MSBuild",),
    )
    for name, prefix in (
        ("Roslynator", "Roslynator"),
        ("SonarAnalyzer", "SonarAnalyzer"),
        ("StyleCop.Analyzers", "StyleCop.Analyzers"),
        ("Meziantou.Analyzer", "Meziantou.Analyzer"),
    )
)
FSHARPLINT = analyzer(
    name="FSharpLint",
    languages=frozenset({FSHARP}),
    how="dotnet fsharplint lint",
    analyses=lambda command, _facts: (
        analysed() if command.argv[:2] in (("fsharplint", "lint"), ("dotnet", "fsharplint")) else None
    ),
)

PACKAGE_REFERENCE = re.compile(r"<PackageReference\b")
LOCKFILE = "packages.lock.json"


def _uses_packages(context: Context) -> str | None:
    texts = (context.project.read_text(path) for path in _settings_files(context))
    return "managed with NuGet" if any(map(PACKAGE_REFERENCE.search, texts)) else None


def _lockfiles(context: Context) -> str | None:
    locks = [path for path in context.tracked_files if PurePosixPath(path).name == LOCKFILE]
    if not locks:
        return None
    return locks[0] if len(locks) == 1 else f"{len(locks)} {LOCKFILE} files"


DEPENDENCIES = DependencyManagement(
    managed=_uses_packages,
    locked=_lockfiles,
    lock_hint="set <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>, commit the packages.lock.json "
    "files, and restore them in CI with --locked-mode",
)

PACKAGE_LICENSE = re.compile(r"<PackageLicenseExpression>\s*([^<]+?)\s*</PackageLicenseExpression>")


def _package_license(context: Context) -> str | None:
    texts = (context.project.read_text(path) for path in _settings_files(context))
    return next((match[1] for text in texts if (match := PACKAGE_LICENSE.search(text))), None)


LICENSE = DeclaredLicense(manifest="the project's PackageLicenseExpression", declared=_package_license)

BUILD_OUTPUT = BuildOutputs(
    name="bin/ and obj/",
    globs=ignored_at_top_level(r"\[Bb\]in|\[Oo\]bj|bin|obj"),
    paths=directories("bin", "obj"),
    hint="consider ignoring bin/ and obj/ (the dotnet new gitignore template does)",
    # bin/ is a common name for scripts too; obj/ and compiled assemblies are .NET's own.
    artifacts=("obj/", "*.dll", "*.pdb", "*.nupkg"),
)

_SDK_VERSION = r"(\d+\.\d+(?:\.[\dx]+)?|\d+\.x)"

DOTNET = Ecosystem(
    label=".NET",
    languages=frozenset({CSHARP, FSHARP}),
    build_systems=(MSBUILD,),
    source_suffixes={".cs": CSHARP, ".fs": FSHARP, ".fsi": FSHARP},
    # F# scripts and Razor views belong to .NET projects, but name no language on their own.
    ambiguous_suffixes={".fsx": None, ".razor": None, ".cshtml": None},
    toolchain=ToolchainPatterns(
        language=".NET SDK",
        versions=(
            re.compile(rf"\bdotnet-version\W+{_SDK_VERSION}"),
            re.compile(rf"\bmcr\.microsoft\.com/dotnet/sdk:{_SDK_VERSION}"),
        ),
        usage=re.compile(r"\bdotnet\s+(?:build|test|restore|publish|pack|run|format)\b|\bsetup-dotnet\b"),
    ),
    rules=(
        versions_axis(".NET SDK version", ".NET SDK"),
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_fsharp_only),
        DEPENDENCIES,
        BUILD_OUTPUT,
        LICENSE,
    ),
)
