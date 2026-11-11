"""Julia: packages described by a `Project.toml`, judged by the Julia versions CI runs and by the Julia code CI runs on
the package: `Pkg.test()` (or julia-actions/julia-runtest), coverage, JuliaFormatter or Runic, and what the tests run
on the package itself (Aqua.jl, JET.jl).

CI runs Julia code in three ways, which `julia_code` reads alike: `julia -e 'using Pkg; Pkg.test()'`, a step whose
`shell: julia --color=yes {0}` runs its script (one `julia` command given the script), and the julia-actions, each an
`Action` that runs the julia command it stands for."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import Strictness, type_checked, type_checker
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.outputs import BuildOutput, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import SettingsReader, file_reader, matched_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either
from project_validator.text import pattern
from project_validator.tools.scanners import multi_language_scanners

JULIA = frozenset({"Julia"})
PROJECT_FILES = ("Project.toml", "JuliaProject.toml")
_PACKAGE_FIELDS = re.compile(r"^(?:name|uuid)\s*=|^\[deps\]", re.MULTILINE)


def _project_languages(_path: str, text: str) -> frozenset[str]:
    """A `Project.toml` naming a package (or its dependencies) is Pkg's; another file so named is not."""
    return JULIA if _PACKAGE_FIELDS.search(text) else frozenset()


PKG = BuildSystem(name="Pkg", files=PROJECT_FILES, declared_languages=_project_languages)
TEST_FILES = ("runtests.jl", "test/*.jl")


def julia_code(command: Command) -> str:
    """The Julia code a command runs: the expressions `julia -e` (or `-E`, `--eval`) is given, or the script it runs
    (its text, for a step with `shell: julia {0}`; its path otherwise); "" for another command."""
    argv = resolved(command)
    if program(argv) != "julia":
        return ""
    expressions = option_values(argv, "-e", "-E", "--eval")
    return "\n".join(expressions or [word for word in argv[1:] if not word.startswith("-")])


# --- Tests, coverage and what the tests run ------------------------------------------------------------------------

JULIA_TEST_FILES = TestFiles(
    name="@test and @testset in test/runtests.jl",
    languages=JULIA,
    path=re.compile(r"(?:^|/)test/.+\.jl$"),
    contains=re.compile(r"@test(?:set|_throws|_broken|_logs)?\b"),
)
_RUNS_TESTS = re.compile(r"\bPkg\.test\s*\(|\bruntests\.jl\b")


def _runs_tests(command: Command) -> bool:
    return _RUNS_TESTS.search(julia_code(command)) is not None


PKG_TEST = test_runner(
    name="Pkg.test",
    languages=JULIA,
    how="Pkg.test() (julia-actions/julia-runtest)",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(JULIA_TEST_FILES.name),
)


def _runtest(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """What julia-actions/julia-runtest runs: `Pkg.test()` with coverage (its default) and the `depwarn` it is given
    (`yes` by default)."""
    coverage = ("--code-coverage=user",) if inputs.get("coverage", "true").lower() != "false" else ()
    depwarn = f"--depwarn={inputs.get('depwarn', 'yes')}"
    return (("julia", "--color=yes", depwarn, *coverage, "-e", "using Pkg; Pkg.test()"),)


JULIA_RUNTEST = Action(name="julia-actions/julia-runtest", runs=_runtest)
# Coverage.jl's process_folder, over the .cov files the tests wrote.
JULIA_PROCESSCOVERAGE = Action(
    name="julia-actions/julia-processcoverage",
    runs=lambda _inputs: (("julia", "-e", "using CoverageTools; process_folder()"),),
)
_COVERAGE_CODE = re.compile(r"\bcoverage\s*=\s*true\b|\bprocess_folder\s*\(|\bCoverage\.(?:process_folder|submit)\b")


def _coverage(command: Command, _facts: Facts) -> Run | None:
    """Julia counts lines (`--code-coverage`, or `Pkg.test(coverage=true)`); Coverage.jl processes the `.cov` files."""
    argv = resolved(command)
    if program(argv) != "julia":
        return None
    counted = has_option(argv, "--code-coverage") or _COVERAGE_CODE.search(julia_code(command)) is not None
    return measured(Granularity.LINE) if counted else None


CODE_COVERAGE = coverage_tool(
    name="julia --code-coverage",
    languages=JULIA,
    can={Granularity.LINE: "julia --code-coverage (julia-actions/julia-runtest, then julia-processcoverage)"},
    measures=_coverage,
)

# Aqua.jl's checks of the package (ambiguities, stale dependencies, piracy) stand in for compiler warnings; JET.jl
# checks the types. Both run inside the tests.
AQUA = pattern("Aqua.test_all", r"\bAqua\.test_(?:all|\w+)\s*\(")
JULIA_TEST_SETTINGS = requirement_reader("Julia tests", TEST_FILES, (required(AQUA),))

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=JULIA,
    requirements=always(required(AQUA)),
    reads=(JULIA_TEST_SETTINGS.name,),
    words=Wording(
        kind="Aqua.jl checks",
        searched="test/runtests.jl and CI configuration",
        hint="run Aqua.test_all(YourPackage) in test/runtests.jl",
    ),
)
# Deprecations are warnings; `--depwarn=error` makes them errors (julia-runtest's `depwarn: error`).
DEPWARN_ERROR = pattern("--depwarn=error", r"\bdepwarn(?:=|:\s*)error\b")
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=JULIA,
    requirements=always(required(DEPWARN_ERROR, in_files=False)),
    any_one=True,
    words=Wording(
        kind="warnings as errors",
        hint="run the tests with --depwarn=error (julia-actions/julia-runtest: depwarn: error)",
    ),
)

_JET = re.compile(r"\bJET\.(?:test_package|report_package|test_call|report_call)\s*\(")


def _read_jet(path: str, text: str) -> Iterator[Setting]:
    return matched_settings("JET", path, text, {"test_package": (_JET, True)})


JET_SETTINGS = SettingsReader(name="JET", files=TEST_FILES, read=_read_jet)


def _jet(command: Command, facts: Facts) -> Run | None:
    """JET checks the package's types when the tests call it and CI runs the tests."""
    configured = facts.where(Setting, tool="JET")
    return type_checked(strict=False, read=configured) if configured and _runs_tests(command) else None


JET = type_checker(
    name="JET.jl",
    languages=JULIA,
    can={Strictness.CHECKS: "JET.test_package(YourPackage) in test/runtests.jl"},
    checks=_jet,
    reads=("JET",),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

JULIAFORMATTER_SETTINGS = file_reader("JuliaFormatter", (".JuliaFormatter.toml",))
_FORMAT = re.compile(r"\bJuliaFormatter\b|\bformat(?:_file)?\s*\(")
_FAILS = re.compile(r"\|\|\s*exit\s*\(\s*1\s*\)|@assert\s+format")


def _juliaformatter(command: Command, facts: Facts) -> Run | None:
    """JuliaFormatter rewrites (`format(".")`); it checks when the script exits non-zero on a file it changed
    (`format(".") || exit(1)`, what julia-actions/julia-format does)."""
    code = julia_code(command)
    if not _FORMAT.search(code):
        return None
    return formatted(command, facts, checks=_FAILS.search(code) is not None)


# JuliaFormatter has a default style; `.JuliaFormatter.toml` picks another. Runic has one style and no settings.
JULIAFORMATTER = format_tool(
    name="JuliaFormatter",
    languages=JULIA,
    can={
        Enforcement.CHECK: "julia -e 'using JuliaFormatter; format(\".\") || exit(1)' (julia-actions/julia-format)",
        Enforcement.APPLY: "julia -e 'using JuliaFormatter; format(\".\")'",
    },
    formats=_juliaformatter,
    style=defined_by(files=(JULIAFORMATTER_SETTINGS.name,)),
)
RUNIC = format_tool(
    name="Runic",
    languages=JULIA,
    can={Enforcement.CHECK: "runic --check . (fredrikekre/runic-action)", Enforcement.APPLY: "runic --inplace ."},
    formats=either(flagged(("runic",), checks=("--check",)), flagged(("julia", "-m", "Runic"), checks=("--check",))),
    style=defined_by(),
)
JULIA_FORMAT = Action(
    name="julia-actions/julia-format",
    runs=lambda inputs: (("julia", "-e", f'using JuliaFormatter; format("{inputs.get("paths", ".")}") || exit(1)'),),
)
RUNIC_ACTION = Action(
    name="fredrikekre/runic-action",
    runs=lambda inputs: (("runic", "--inplace" if inputs.get("format_files") == "true" else "--check", "."),),
)

# semgrep reads Julia; CodeQL and GitLab SAST do not.
SECURITY_SCANNERS = tuple(tool for tool in multi_language_scanners(JULIA) if tool.name == "semgrep")


# --- Outputs --------------------------------------------------------------------------------------------------------

COVERAGE_FILES = BuildOutput(
    languages=JULIA,
    name="the coverage files (*.jl.cov)",
    globs=ignored_at_top_level(r"\*\.jl\.cov|\*\.jl\.\*\.cov|\*\.cov"),
    paths=("src/Shop.jl.cov", "src/Shop.jl.1234.cov"),
    hint="consider ignoring *.jl.cov and *.jl.*.cov",
    artifacts=("*.cov",),
)
MEMORY_FILES = BuildOutput(
    languages=JULIA,
    name="the allocation files (*.jl.mem)",
    globs=ignored_at_top_level(r"\*\.jl\.mem|\*\.mem"),
    paths=("src/Shop.jl.mem",),
    hint="consider ignoring *.jl.mem",
    artifacts=("*.mem",),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# julia-actions/setup-julia's `version`: a version or a range (`1`, `1.10`, `^1.6`), `lts`, `pre`, `nightly`, `min`.
# An input called `version` is any action's, so it counts after setup-julia's `uses:` line only; a matrix key called
# `julia-version` or `julia` is Julia's.
_JULIA_VERSION = r"([~^]?\d+(?:\.\d+){0,2}|lts|pre|nightly|min)"

JULIA_ECOSYSTEM = Ecosystem(
    label="Julia",
    languages=JULIA,
    build_systems=(PKG,),
    source_suffixes={".jl": "Julia"},
    toolchain=toolchain_patterns(
        "Julia",
        version=_JULIA_VERSION,
        inputs=("julia-version",),
        images=("julia",),
        more=(
            rf"\buses: julia-actions/setup-julia@[^\n]*\n(?:(?!uses:)[^\n]*\n)*?version:\s*[\"']?{_JULIA_VERSION}\b",
            rf"\"julia(?:-version)?\":\s*\"{_JULIA_VERSION}\"",
            rf"\bjuliaup\s+(?:add|default)\s+{_JULIA_VERSION}\b",
        ),
        commands=r"\bjulia\b|\bjuliaup\b|\bjulia-actions/",
        setup=("julia",),
    ),
)

JULIA_VERSIONS = versions_axis("Julia version", "Julia", JULIA)
