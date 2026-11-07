"""The .NET profile's rules, judged by the generic checks in the MSBuild project layouts."""

import unittest

from project_validator.core import Result, Status
from project_validator.ecosystems.dotnet import BUILD_OUTPUT, DEPENDENCIES, DOTNET
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, make_context, run_as, run_in_layout, temp_project

(
    CODE_FORMATTING,
    COMPILER_WARNINGS,
    COVERAGE,
    DEPENDENCY_AUDIT,
    DEPENDENCY_MANAGEMENT,
    FUNCTION_LIMITS,
    LICENSE,
    PLATFORM_MATRIX,
    SECURITY_SCANNING,
    STATIC_ANALYSIS,
    TESTS_RUN,
    WARNINGS_AS_ERRORS,
) = checks_named(
    "code-formatting",
    "compiler-warnings",
    "coverage",
    "dependency-audit",
    "dependency-management",
    "function-limits",
    "license",
    "platform-matrix",
    "security-scanning",
    "static-analysis",
    "tests-run",
    "warnings-as-errors",
)
BUILD = "dotnet build -c Release"
CSHARP = "MSBuild C#"
FSHARP = "MSBuild F#"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _props(*properties: str, items: str = "") -> dict[str, str]:
    group = "".join(f"<{name}>{value}</{name}>" for name, value in (p.split("=", 1) for p in properties))
    return {"Directory.Build.props": f"<Project><PropertyGroup>{group}</PropertyGroup>{items}</Project>\n"}


TEST_PROJECT = {
    "tests/App.Tests/App.Tests.csproj": '<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1" />',
    "tests/App.Tests/AddTests.cs": "public class AddTests { [Fact] public void Adds() {} }\n",
}
PACKAGES = _props(items='<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" /></ItemGroup>')


class RecognitionTests(unittest.TestCase):
    def test_bin_and_obj_beside_a_project_are_build_output(self) -> None:
        files = {"App.csproj": "", "obj/Generated.cs": "", "tools/bin/Run.fs": ""}
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"F#"}))

    def test_project_and_solution_files_are_build_files_that_name_no_language(self) -> None:
        with temp_project({"App.slnx": "", "global.json": "{}", "Directory.Build.props": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (frozenset(), frozenset({"MSBuild"})))


class BuildSettingTests(unittest.TestCase):
    def test_analyzers_count_when_ci_builds(self) -> None:
        props = _props("AnalysisLevel=latest-recommended", "EnforceCodeStyleInBuild=true", "Nullable=enable")
        result = run_in_layout(self, CSHARP, COMPILER_WARNINGS, {**props, **_ci(BUILD)})
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(run_in_layout(self, CSHARP, COMPILER_WARNINGS, props).status, Status.FAIL)
        partial = run_in_layout(self, CSHARP, COMPILER_WARNINGS, _ci(f"{BUILD} -p:Nullable=enable"))
        expected = "missing .NET analyzer settings: AnalysisMode Recommended or All, EnforceCodeStyleInBuild"
        self.assertEqual(partial.message, expected)

    def test_fsharp_turns_on_compiler_warnings(self) -> None:
        props = _props("WarnOn=3390;1182")
        self.assertEqual(run_in_layout(self, FSHARP, COMPILER_WARNINGS, {**props, **_ci(BUILD)}).status, Status.PASS)
        self.assertEqual(run_in_layout(self, FSHARP, COMPILER_WARNINGS, _ci(BUILD)).status, Status.FAIL)

    def test_warnings_as_errors_in_a_project_or_on_the_command_line(self) -> None:
        for files in ({**_props("TreatWarningsAsErrors=true"), **_ci("dotnet test")}, _ci(f"{BUILD} -warnaserror")):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, files, DOTNET).status, Status.PASS)
        # Making only some warnings errors is not treating warnings as errors.
        only_some = _ci(f"{BUILD} -warnaserror:CS8602")
        self.assertEqual(run_as(self, WARNINGS_AS_ERRORS, only_some, DOTNET).status, Status.FAIL)

    def test_formatters_check_without_changing(self) -> None:
        # dotnet format and CSharpier format C#; Fantomas formats F#.
        for layout, command in (
            (CSHARP, "dotnet format --verify-no-changes"),
            (CSHARP, "dotnet csharpier check ."),
            (CSHARP, "csharpier --check ."),
            (FSHARP, "dotnet fantomas --check ."),
        ):
            with self.subTest(command=command):
                self.assertEqual(run_in_layout(self, layout, CODE_FORMATTING, _ci(command)).status, Status.PASS)
                other = FSHARP if layout == CSHARP else CSHARP
                self.assertEqual(run_in_layout(self, other, CODE_FORMATTING, _ci(command)).status, Status.FAIL)
        rewritten = run_in_layout(self, CSHARP, CODE_FORMATTING, _ci("dotnet format"))
        self.assertEqual(rewritten.status, Status.FAIL)
        self.assertIn("only to rewrite files", rewritten.message)


class TestAndCoverageTests(unittest.TestCase):
    def test_tests_need_a_test_project(self) -> None:
        files = {**TEST_PROJECT, **_ci("dotnet test")}
        self.assertEqual(run_in_layout(self, CSHARP, TESTS_RUN, files), Result.passed("tests found in 1 file(s)"))
        no_sdk = {"tests/AddTests.cs": "[Fact] void Adds() {}"}
        self.assertIn("no tests found", run_in_layout(self, CSHARP, TESTS_RUN, no_sdk).message)
        no_tests = {"tests/App.Tests/App.Tests.csproj": '<Project Sdk="MSTest.Sdk/3.9.3" />'}
        self.assertIn("no tests found", run_in_layout(self, CSHARP, TESTS_RUN, no_tests).message)

    def test_fsharp_tests_have_attributes_too(self) -> None:
        files = {"App.Tests.fsproj": '<Project Sdk="MSTest.Sdk" />', "Tests.fs": "[<Fact>]\nlet adds () = ()\n"}
        self.assertEqual(run_in_layout(self, FSHARP, TESTS_RUN, {**files, **_ci("dotnet test")}).status, Status.PASS)

    def test_coverage_is_coverlet_or_microsofts_tools(self) -> None:
        settings = {"coverage.runsettings": '<DataCollector friendlyName="XPlat code coverage" />'}
        for files in (
            _ci('dotnet test --collect "XPlat Code Coverage"'),
            _ci("dotnet test /p:CollectCoverage=true"),
            _ci("dotnet-coverage collect dotnet test"),
            _ci("dotnet test --coverage --coverage-output-format cobertura"),
            {**settings, **_ci("dotnet test --settings coverage.runsettings")},
            {
                **settings,
                **_props("RunSettingsFilePath=./coverage.runsettings"),
                **_ci("dotnet test"),
            },
            {**_props("CollectCoverage=true"), **_ci("dotnet test")},
            _ci("coverlet tests/bin/App.Tests.dll --target dotnet"),
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, DOTNET).status, Status.PASS)
        # Settings count when CI runs the tests that read them.
        for files in (settings, {**settings, **_ci("dotnet test")}, _props("CollectCoverage=true")):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, COVERAGE, files, DOTNET).status, Status.FAIL)


class SecurityAndAnalysisTests(unittest.TestCase):
    def test_nuget_audit_of_every_package_or_a_vulnerable_listing(self) -> None:
        for files in (
            {**_props("NuGetAuditMode=all"), **_ci("dotnet restore")},
            _ci("dotnet list package --vulnerable --include-transitive"),
            _ci("dotnet package list --vulnerable"),
        ):
            with self.subTest(files=files):
                self.assertEqual(run_as(self, DEPENDENCY_AUDIT, files, DOTNET).status, Status.PASS)
        direct_only = {**_props("NuGetAuditMode=direct"), **_ci("dotnet restore")}
        self.assertEqual(run_as(self, DEPENDENCY_AUDIT, direct_only, DOTNET).status, Status.WARN)

    def test_security_analyzers_or_security_code_scan(self) -> None:
        editorconfig = {".editorconfig": "[*.cs]\ndotnet_analyzer_diagnostic.category-Security.severity = error\n"}
        package = _props(items='<ItemGroup><PackageReference Include="SecurityCodeScan.VS2019" /></ItemGroup>')
        mode = _props("AnalysisModeSecurity=Recommended")
        for files in (editorconfig, package, mode):
            with self.subTest(files=files):
                built = {**files, **_ci(BUILD)}
                self.assertEqual(run_in_layout(self, CSHARP, SECURITY_SCANNING, built).status, Status.PASS)
                # The analyzers run when CI builds the project.
                self.assertEqual(run_in_layout(self, CSHARP, SECURITY_SCANNING, files).status, Status.WARN)

    def test_an_analyzer_package_is_static_analysis(self) -> None:
        package = _props(items='<ItemGroup><PackageReference Include="StyleCop.Analyzers" /></ItemGroup>')
        result = run_in_layout(self, CSHARP, STATIC_ANALYSIS, {**package, **_ci(BUILD)})
        self.assertEqual(result, Result.passed("StyleCop.Analyzers (Directory.Build.props) runs"))
        # Analyzer packages analyse C#; FSharpLint analyses F#.
        self.assertEqual(run_in_layout(self, FSHARP, STATIC_ANALYSIS, {**package, **_ci(BUILD)}).status, Status.FAIL)
        fsharplint = _ci("dotnet fsharplint lint App.fsproj")
        self.assertEqual(run_in_layout(self, FSHARP, STATIC_ANALYSIS, fsharplint).status, Status.PASS)
        self.assertEqual(
            run_in_layout(self, CSHARP, STATIC_ANALYSIS, {**package, **_ci("dotnet restore")}).status, Status.WARN
        )

    def test_function_length_is_measured_by_lizard_except_for_fsharp(self) -> None:
        self.assertEqual(run_in_layout(self, CSHARP, FUNCTION_LIMITS, {}).status, Status.FAIL)
        skipped = run_in_layout(self, FSHARP, FUNCTION_LIMITS, {})
        # No known tool limits the length of F# functions.
        self.assertEqual(skipped.status, Status.SKIP)


class DependencyTests(unittest.TestCase):
    def test_package_references_are_locked_by_lock_files(self) -> None:
        expected = Result.warned("dependencies are managed with NuGet but not locked", DEPENDENCIES.lock_hint)
        self.assertEqual(run_as(self, DEPENDENCY_MANAGEMENT, PACKAGES, DOTNET), expected)
        locked = run_as(self, DEPENDENCY_MANAGEMENT, {**PACKAGES, "packages.lock.json": "{}"}, DOTNET)
        self.assertEqual(locked.message, "dependencies are managed with NuGet and locked in packages.lock.json")

    def test_the_package_license_expression_is_the_declared_license(self) -> None:
        mit = "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        files = {"LICENSE": mit, **_props("PackageLicenseExpression=Apache-2.0")}
        result = run_in_layout(self, CSHARP, LICENSE, files)
        self.assertIn("PackageLicenseExpression declares Apache-2.0", result.details[0])

    def test_object_directories_and_assemblies_are_outputs(self) -> None:
        self.assertEqual(BUILD_OUTPUT.artifact("src/App/obj/project.assets.json"), "src/App/obj/")
        self.assertEqual(BUILD_OUTPUT.artifact("lib/Newtonsoft.Json.dll"), "lib/Newtonsoft.Json.dll")
        self.assertIsNone(BUILD_OUTPUT.artifact("bin/release.sh"))

    def test_the_platform_matrix_counts_sdk_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  linux:
                    runs-on: ubuntu-latest
                    container: mcr.microsoft.com/dotnet/sdk:10.0
                    steps:
                      - run: dotnet test
                  windows:
                    runs-on: windows-latest
                    steps:
                      - uses: actions/setup-dotnet@v4
                        with:
                          dotnet-version: 9.0.x
                """
        }
        self.assertIn("2 .NET SDK version(s) (10.0, 9.0.x)", run_as(self, PLATFORM_MATRIX, files, DOTNET).message)
