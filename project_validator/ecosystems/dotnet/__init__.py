""".NET (C# and F#): built with MSBuild and the dotnet CLI, judged by the .NET SDK versions CI runs.

A .NET build reads its settings (analyzers, warnings, coverage, auditing) from the project files and
Directory.Build.props, so those count as CI configuration when CI builds the project."""

from __future__ import annotations

import re
from collections.abc import Iterator
from fnmatch import fnmatchcase
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.tools import Claim, Definition, Run

CSHARP = "C#"


FSHARP = "F#"


DOTNET_LANGUAGES = frozenset({CSHARP, FSHARP})


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


def msbuild_property(name: str, values: str) -> str:
    """An MSBuild property set to one of `values`, in a project file or on the command line."""
    return rf"<{name}>\s*(?:{values})\s*</{name}>|[-/]p(?:roperty)?:{name}=(?:{values})\b"


# The commands that build a project, and so run the analyzers its packages add.
_BUILDS = frozenset({"build", "test", "pack", "publish", "run", "msbuild"})


def builds_project(command: Command) -> bool:
    """Whether a command builds a project, and so runs the analyzers it references."""
    argv = resolved(command)
    return program(argv) in ("msbuild", "MSBuild") or (
        program(argv) == "dotnet" and argv[1:2] != () and argv[1] in _BUILDS
    )


def _analyzer_package(prefix: str) -> Claim:
    """An analyzer a NuGet package adds to the compiler, which runs on every build of a project that references it."""

    def analyses(command: Command, facts: Facts) -> Run | None:
        references = facts.where(Setting, tool="MSBuild", key="PackageReference")
        read = [found for found in references if str(found.value).lower().startswith(prefix.lower())]
        return analysed(read=read) if builds_project(command) and read else None

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


PACKAGE_REFERENCE = re.compile(r"<PackageReference\b")


LOCKFILE = "packages.lock.json"


NUGET_DEPENDENCIES = manifest_reader(
    name="NuGet package references",
    manager="NuGet",
    files=SETTINGS_FILES,
    declares=lambda _path, text: bool(PACKAGE_REFERENCE.search(text)),
)


NUGET_LOCKFILES = lockfile_reader(manager="NuGet", files=(LOCKFILE,))


NUGET_PACKAGES = PackageManager(
    name="NuGet",
    languages=DOTNET_LANGUAGES,
    lock_hint="set <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>, commit the packages.lock.json "
    "files, and restore them in CI with --locked-mode",
)


PACKAGE_LICENSE = re.compile(r"<PackageLicenseExpression>\s*([^<]+?)\s*</PackageLicenseExpression>")


def _package_license(text: str) -> str | None:
    return match[1] if (match := PACKAGE_LICENSE.search(text)) else None


PACKAGE_LICENSE_EXPRESSION = declared_license_reader(
    name="PackageLicenseExpression", files=SETTINGS_FILES, languages=DOTNET_LANGUAGES, declared=_package_license
)


BUILD_OUTPUT = BuildOutput(
    languages=DOTNET_LANGUAGES,
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
    toolchain=toolchain_patterns(
        ".NET SDK",
        version=_SDK_VERSION,
        inputs=("dotnet-version",),
        images=("mcr.microsoft.com/dotnet/sdk",),
        programs=subcommands("dotnet", "build", "test", "restore", "publish", "pack", "run", "format"),
        setup=("dotnet",),
    ),
)


DOTNET_SDK_VERSIONS = versions_axis(".NET SDK version", ".NET SDK", DOTNET_LANGUAGES)
