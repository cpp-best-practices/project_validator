""".NET (C# and F#): built with MSBuild and the dotnet CLI, judged by the .NET SDK versions CI runs.

A .NET build reads its settings (analyzers, warnings, coverage, auditing) from the project files and
Directory.Build.props, so those count as CI configuration when CI builds the project.
"""

import re
from collections.abc import Callable
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from project_validator.core import Context, Result, Status
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import ci_and_hook_texts, configuration, existing_texts
from project_validator.rules import (
    MULTI_ECOSYSTEM_AUDITS,
    SUGGESTED_LIZARD,
    Analyzer,
    BuildOutputs,
    CoverageTools,
    DeclaredLicense,
    DependencyAudit,
    DependencyManagement,
    Formatter,
    FunctionLimits,
    SecurityLints,
    StaticAnalysis,
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


def _coverage_texts(context: Context) -> tuple[str, ...]:
    """The build's texts, and the .runsettings files that configure test runs."""
    settings = [path for path in context.project.files() if path.endswith(".runsettings")]
    return (*_build_texts(context), *(context.project.read_text(path) for path in settings))


def _with_files(*files: str) -> Callable[[Context], tuple[str, ...]]:
    def texts(context: Context) -> tuple[str, ...]:
        return (*_build_texts(context), *existing_texts(context, files))

    return texts


def _property(name: str, values: str) -> str:
    """An MSBuild property set to one of `values`, in a project file or on the command line."""
    return rf"<{name}>\s*(?:{values})\s*</{name}>|[-/]p(?:roperty)?:{name}=(?:{values})\b"


# Each of them has a default style: dotnet format reads .editorconfig, and CSharpier and Fantomas have their own.
FORMATTERS = Formatter(
    name="dotnet format, CSharpier or Fantomas",
    config_file=configuration((".editorconfig", ".csharpierrc", ".csharpierrc.json", ".csharpierrc.yaml")),
    runs=(
        pattern("dotnet format", r"\bdotnet\s+format\b[^\n]*--verify-no-changes\b"),
        pattern("CSharpier", r"\bcsharpier\s+(?:check\b|[^\n]*--check\b)"),
        pattern("Fantomas", r"\bfantomas\b[^\n]*--check\b"),
    ),
    hint="consider a CI job that runs dotnet format --verify-no-changes (or csharpier check, or fantomas --check)",
    default_style=True,
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

# coverlet, Microsoft's dotnet-coverage and Microsoft.Testing.Platform's coverage all count branches.
COVERAGE = CoverageTools(
    searched="CI configuration, the MSBuild settings it builds with, or a .runsettings file",
    texts=_coverage_texts,
    branch=(
        pattern("coverlet", rf"XPlat Code Coverage|{_property('CollectCoverage', 'true')}"),
        pattern("dotnet-coverage", r"\bdotnet-coverage\s+collect\b"),
        pattern("Microsoft.Testing.Platform --coverage", r"\bdotnet\s+test\b[^\n]*\s--coverage\b"),
    ),
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


def _package(name: str) -> re.Pattern[str]:
    return re.compile(rf"""Include\s*=\s*["']{re.escape(name)}\b""", re.IGNORECASE)


STATIC_ANALYSIS = StaticAnalysis(
    analyzers=(
        Analyzer(name="Roslynator", runs=_package("Roslynator")),
        Analyzer(name="SonarAnalyzer", runs=_package("SonarAnalyzer")),
        Analyzer(name="StyleCop.Analyzers", runs=_package("StyleCop.Analyzers")),
        Analyzer(name="Meziantou.Analyzer", runs=_package("Meziantou.Analyzer")),
        Analyzer(name="FSharpLint", runs=re.compile(r"\bfsharplint\s+lint\b", re.IGNORECASE)),
    ),
    texts=_build_texts,
    hint="consider an analyzer package beyond the SDK's own (Roslynator, SonarAnalyzer, StyleCop.Analyzers or "
    "Meziantou.Analyzer; FSharpLint for F#)",
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
        FORMATTERS,
        COVERAGE,
        TESTS,
        WARNINGS,
        WARNINGS_AS_ERRORS,
        SECURITY_LINTS,
        DEPENDENCY_AUDIT,
        FunctionLimits(without_lizard=_fsharp_only),
        STATIC_ANALYSIS,
        DEPENDENCIES,
        BUILD_OUTPUT,
        LICENSE,
    ),
)
