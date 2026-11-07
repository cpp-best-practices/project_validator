# .NET

C# and F#, recognised by `.cs` and `.fs` sources and MSBuild project and solution files. Project files and
`Directory.Build.props` count as CI configuration when CI builds.

## `tests-run`

A test project referencing `Microsoft.NET.Test.Sdk` (or `MSTest.Sdk`) with `[Fact]`, `[Test]` or `[TestMethod]`
tests, run by `dotnet test`.

## `coverage`

coverlet (`dotnet test --collect "XPlat Code Coverage"`, `CollectCoverage=true` on the command line or in the MSBuild
settings `dotnet test` builds with, a `.runsettings` file it is given that adds the collector, or the `coverlet`
console tool), `dotnet-coverage collect` or `dotnet test --coverage`.

## `platform-matrix`

The toolchains are .NET SDK versions.

## `compiler-warnings`

C# projects set `AnalysisMode` (or `AnalysisLevel`) to Recommended or All, `EnforceCodeStyleInBuild` and `Nullable`
`enable` in a project file or `Directory.Build.props`; F#-only projects turn on more compiler warnings (`<WarnOn>`,
`--warnon:`).

## `warnings-as-errors`

`TreatWarningsAsErrors` or `-warnaserror`.

## `code-formatting`

`dotnet format --verify-no-changes`, `csharpier check` or `fantomas --check`; they have a default style, so CI
enforcement alone passes.

## `function-limits`

lizard runs with a length limit. lizard does not measure F#, so F#-only projects are skipped.

## `static-analysis`

An analyzer package beyond the SDK's own (Roslynator, SonarAnalyzer, StyleCop.Analyzers or Meziantou.Analyzer), or
FSharpLint.

## `security-scanning`

The analyzers' Security category (`AnalysisModeSecurity`, or `category-Security` severity warning or error in
`.editorconfig`), or Security Code Scan.

## `dependency-management`

NuGet `PackageReference`s are locked by committed `packages.lock.json` files.

## `dependency-audit`

`NuGetAuditMode` `all` (restoring then audits transitive packages too) or `dotnet list package --vulnerable`.

## `license`

`PackageLicenseExpression`.

## `committed-artifacts`

`obj/`, `*.dll`, `*.pdb` and `*.nupkg`.

## `vcs-ignore`

`bin/` or `obj/`.

`hardening` is not judged for .NET yet.
