""".NET's practices: the settings it asks for, and how they are worded (see
`project_validator.facts.practices`)."""

from __future__ import annotations

import re

from project_validator.ecosystems.dotnet import CSHARP, DOTNET_LANGUAGES, FSHARP, SETTINGS_FILES, msbuild_property
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.text import Pattern, pattern

ANALYSIS_MODE = Pattern(
    "AnalysisMode Recommended or All",
    re.compile(
        r"<AnalysisMode>\s*(?:Recommended|All)\s*</AnalysisMode>"
        r"|<AnalysisLevel>\s*[\w.]*-?(?:recommended|all)\s*</AnalysisLevel>",
        re.IGNORECASE,
    ),
)


ENFORCE_CODE_STYLE = Pattern(
    "EnforceCodeStyleInBuild", re.compile(msbuild_property("EnforceCodeStyleInBuild", "true"), re.I)
)


NULLABLE = Pattern("Nullable enable", re.compile(msbuild_property("Nullable", "enable"), re.IGNORECASE))


# The .NET analyzers do not analyze F#; its compiler has warnings to turn on.
FSHARP_WARNINGS = Pattern("F# --warnon", re.compile(r"<WarnOn>[^<]+</WarnOn>|--warnon:\S+", re.IGNORECASE))


_CSHARP_WARNINGS = (required(ANALYSIS_MODE), required(ENFORCE_CODE_STYLE), required(NULLABLE))


_FSHARP_WARNINGS = (required(FSHARP_WARNINGS),)


_DOTNET_WARNINGS_AS_ERRORS = (
    required(
        pattern(
            "TreatWarningsAsErrors",
            rf"{msbuild_property('TreatWarningsAsErrors', 'true')}|(?<![\w-])[-/]{{1,2}}warnaserror(?![\w:-])",
        )
    ),
)


DOTNET_WARNING_SETTINGS = requirement_reader(
    "MSBuild warning settings", SETTINGS_FILES, (*_CSHARP_WARNINGS, *_FSHARP_WARNINGS, *_DOTNET_WARNINGS_AS_ERRORS)
)


# The .NET analyzers analyze C#; F#'s compiler has warnings to turn on instead.
CSHARP_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({CSHARP}),
    requirements=always(*_CSHARP_WARNINGS),
    reads=(DOTNET_WARNING_SETTINGS.name,),
    words=Wording(
        kind=".NET analyzer settings",
        hint="set <AnalysisMode>All</AnalysisMode>, <EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild> and "
        "<Nullable>enable</Nullable> in Directory.Build.props",
    ),
)


FSHARP_WARNINGS_PRACTICE = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({FSHARP}),
    requirements=always(*_FSHARP_WARNINGS),
    reads=(DOTNET_WARNING_SETTINGS.name,),
    words=Wording(
        kind=".NET analyzer settings",
        hint="turn on F# warnings with <WarnOn> (or --warnon:)",
    ),
)


WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=DOTNET_LANGUAGES,
    requirements=always(*_DOTNET_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(DOTNET_WARNING_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="the MSBuild settings or CI configuration",
        hint="set <TreatWarningsAsErrors>true</TreatWarningsAsErrors> in Directory.Build.props",
    ),
)
