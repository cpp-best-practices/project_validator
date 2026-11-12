"""Perl: distributions built with ExtUtils::MakeMaker, Module::Build or Dist::Zilla (and a `cpanfile` of
dependencies), judged by the Perl versions CI runs, by the pragmas every module starts with and by the tools CI runs on
the code: prove, Devel::Cover, perltidy, perlcritic and cpan-audit."""

from __future__ import annotations

import re
from collections.abc import Iterator

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import (
    Evidence,
    Practice,
    PracticeName,
    Requirement,
    Wording,
    always,
    requirement_reader,
)
from project_validator.facts.settings import SettingsReader, file_reader, settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, starts, when
from project_validator.tools.limits import function_length_limiters

PERL = frozenset({"Perl"})

MAKEMAKER = BuildSystem(name="ExtUtils::MakeMaker", files=("Makefile.PL",), languages=PERL)
MODULE_BUILD = BuildSystem(name="Module::Build", files=("Build.PL",), languages=PERL)
DIST_ZILLA = BuildSystem(name="Dist::Zilla", files=("dist.ini",), languages=PERL)
# A cpanfile declares the dependencies (for cpanm, cpm or Carton), with or without a distribution around it.
CPANFILE = BuildSystem(name="cpanfile", files=("cpanfile",), languages=PERL)
DISTRIBUTIONS = frozenset({MAKEMAKER.name, MODULE_BUILD.name, DIST_ZILLA.name})
BUILD_SYSTEMS = DISTRIBUTIONS | {CPANFILE.name}


# --- Tests and coverage ---------------------------------------------------------------------------------------------

PERL_TEST_FILES = TestFiles(
    name="Test::More or Test2 tests in t/*.t",
    languages=PERL,
    path=re.compile(r"(?:^|/)x?t/.+\.t$"),
    contains=re.compile(
        r"^\s*use\s+Test(?:2|::More|::Most|::Simple)\b|\b(?:ok|is|is_deeply|like|cmp_ok|subtest|done_testing)\s*\(",
        re.MULTILINE,
    ),
)


def _runs_tests(command: Command) -> bool:
    """prove, the build systems' `test` targets, Dist::Zilla's and Minilla's `test`, Test2's yath, or Devel::Cover's
    `cover -test`, which runs the tests instrumented."""
    argv = resolved(command)
    prefixes = (("prove",), ("make", "test"), ("Build", "test"), ("perl", "Build", "test"), ("dzil", "test"))
    if starts_with(argv, *prefixes, ("minil", "test"), ("yath", "test")) is not None:
        return True
    return program(argv) == "cover" and "-test" in argv


PROVE = test_runner(
    name="prove",
    languages=PERL,
    how="prove -l t (or make test, ./Build test, dzil test)",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(PERL_TEST_FILES.name),
)

_WITH_DEVEL_COVER = re.compile(r"-MDevel::Cover\b")


def _devel_cover(command: Command, _facts: Facts) -> Run | None:
    """Devel::Cover counts statements, branches and conditions (the bonus): `cover -test` (and `cover -report`), or
    the tests run with `HARNESS_PERL_SWITCHES=-MDevel::Cover`."""
    argv = resolved(command)
    instrumented = _WITH_DEVEL_COVER.search(command.env.get("HARNESS_PERL_SWITCHES", "")) and _runs_tests(command)
    if program(argv) == "cover" or instrumented:
        return measured(Granularity.STATEMENT, Granularity.BRANCH, Granularity.PATH)
    return None


DEVEL_COVER = coverage_tool(
    name="Devel::Cover",
    languages=PERL,
    can={
        Granularity.STATEMENT: "cover -test",
        Granularity.BRANCH: "cover -test",
        Granularity.PATH: "cover -test (condition coverage)",
    },
    measures=_devel_cover,
)


# --- Formatting -----------------------------------------------------------------------------------------------------

PERLTIDY_SETTINGS = file_reader("perltidy", (".perltidyrc", "perltidyrc", ".perltidyrc.toml"))

# perltidy has a default style; `.perltidyrc` holds the project's. tidyall runs it (and perlcritic) over the project.
PERLTIDY = format_tool(
    name="perltidy",
    languages=PERL,
    can={Enforcement.CHECK: "perltidy --assert-tidy (or tidyall --check-only)", Enforcement.APPLY: "perltidy -b"},
    formats=lambda command, facts: (
        flagged(("perltidy",), checks=("--assert-tidy", "-ast"))(command, facts)
        or flagged(("tidyall",), checks=("--check-only", "-c"))(command, facts)
    ),
    style=defined_by(files=(PERLTIDY_SETTINGS.name,)),
)


# --- Pragmas, lints and warnings ------------------------------------------------------------------------------------

MODULES = "Perl modules"
_USE = r"^\s*use\s+"
# Pragmas and frameworks that turn `strict` (and `warnings`) on for the module that uses them.
_STRICT = re.compile(rf"{_USE}strict\b", re.MULTILINE)
_WARNINGS = re.compile(rf"{_USE}warnings\b", re.MULTILINE)
_IMPLIES_BOTH = re.compile(
    rf"{_USE}(?:Moose|Moo|Mouse|Moose::Role|Moo::Role|Mouse::Role|Modern::Perl|common::sense|strictures|Mojo::Base"
    r"|Mojolicious::Lite|Role::Tiny|Test2::V0|Object::Pad|Dancer2?|v5\.(?:3[5-9]|[4-9]\d)|experimental)\b",
    re.MULTILINE,
)
# `use v5.12` and later turn strict on; warnings only from v5.35.
_IMPLIES_STRICT = re.compile(rf"{_USE}v5\.(?:1[2-9]|[2-9]\d)\b", re.MULTILINE)


def _read_modules(path: str, text: str) -> Iterator[Setting]:
    """Whether a module (or script) starts with `use strict` and `use warnings`, or something that implies them."""
    both = _IMPLIES_BOTH.search(text) is not None
    strict = both or _STRICT.search(text) is not None or _IMPLIES_STRICT.search(text) is not None
    warnings = both or _WARNINGS.search(text) is not None
    return settings(MODULES, path, (("strict", strict), ("warnings", warnings)))


PERL_MODULES = SettingsReader(name=MODULES, files=("*.pm", "*.pl", "*.psgi"), read=_read_modules)


def _every_module(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
    """Every module read uses strict and warnings: one that does not fails all of them."""
    found = facts.where(Setting, tool=MODULES)
    paths = {setting.path for setting in found}
    if paths and all(setting.value for setting in found):
        yield Evidence(f"{len(paths)} module(s), every one")


STRICT_AND_WARNINGS = Requirement(name="use strict and use warnings in every module", found=_every_module)
PERLCRITIC = Requirement(
    name="perlcritic",
    runs=re.compile(r"(?<![\w:])perlcritic\b"),
    pattern=re.compile(rf"{_USE}Test::Perl::Critic\b", re.MULTILINE),
)
FATAL_WARNINGS = Requirement(
    name="use warnings FATAL => 'all'", pattern=re.compile(rf"{_USE}warnings\s+FATAL\s*=>\s*['\"]all", re.MULTILINE)
)
TEST_WARNINGS = Requirement(
    name="Test::Warnings in the tests",
    pattern=re.compile(rf"{_USE}Test::(?:Warnings|NoWarnings|FailWarnings)\b", re.MULTILINE),
)
PERL_PRAGMAS = requirement_reader("Perl pragmas", ("*.pm", "*.pl", "*.psgi"), (FATAL_WARNINGS,))
PERL_TEST_SETTINGS = requirement_reader("Perl tests", ("*.t",), (PERLCRITIC, TEST_WARNINGS))

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=PERL,
    requirements=always(STRICT_AND_WARNINGS, PERLCRITIC),
    reads=(MODULES, PERL_TEST_SETTINGS.name),
    words=Wording(
        kind="Perl pragmas and lints",
        searched="the modules, the tests and CI configuration",
        hint="start every module with use strict and use warnings (or a module that implies them: Moose, Moo, "
        "Modern::Perl, use v5.36) and run perlcritic in CI (or Test::Perl::Critic in the tests)",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=PERL,
    requirements=always(FATAL_WARNINGS, TEST_WARNINGS),
    any_one=True,
    reads=(PERL_PRAGMAS.name, PERL_TEST_SETTINGS.name),
    words=Wording(
        kind="warnings as errors",
        searched="the modules and the tests",
        hint="use warnings FATAL => 'all' in the modules, or use Test::Warnings (or Test::NoWarnings) in the tests, "
        "which fail on a warning",
    ),
)

PERLCRITIC_SETTINGS = file_reader("perlcritic", (".perlcriticrc", "perlcriticrc"))
PERLCRITIC_ANALYZER = analyzer(
    name="perlcritic",
    languages=PERL,
    how="perlcritic lib t",
    analyses=when(starts(("perlcritic",), ("tidyall",)), analysed),
    rules=defined_by(files=(PERLCRITIC_SETTINGS.name,)),
)

CPAN_AUDIT = auditor(
    name="cpan-audit",
    languages=PERL,
    how="cpan-audit deps . (CPAN::Audit)",
    audits=when(starts(("cpan-audit",)), audited),
)

FUNCTION_LENGTH_LIMITERS = function_length_limiters(PERL)


# --- Outputs --------------------------------------------------------------------------------------------------------


def _output(
    name: str, globs: str, paths: tuple[str, ...], hint: str, artifacts: tuple[str, ...], tied: frozenset[str]
) -> BuildOutput:
    return BuildOutput(
        languages=PERL,
        build_systems=tied,
        name=name,
        globs=ignored_at_top_level(globs),
        paths=paths,
        hint=hint,
        artifacts=artifacts,
    )


BLIB = _output(
    "the blib build directory", "blib", directories("blib"), "consider ignoring blib/", ("/blib/",), DISTRIBUTIONS
)
MYMETA = _output(
    "the MYMETA files",
    r"MYMETA\.\*|MYMETA\.(?:json|yml)",
    ("MYMETA.json", "MYMETA.yml"),
    "consider ignoring MYMETA.*",
    ("MYMETA.json", "MYMETA.yml"),
    frozenset({MAKEMAKER.name, MODULE_BUILD.name}),
)
BUILD_DIRECTORY = _output(
    "Module::Build's _build directory",
    "_build",
    directories("_build"),
    "consider ignoring _build/ (and the Build script)",
    ("/_build/",),
    frozenset({MODULE_BUILD.name}),
)
CARTON_LOCAL = _output(
    "Carton's local directory",
    "local",
    directories("local"),
    "consider ignoring local/ (carton install writes it)",
    ("/local/",),
    frozenset({CPANFILE.name}),
)
# Devel::Cover's database, for distributions (whose outputs hide the language-wide ones) and for plain scripts alike.
COVER_DB, COVER_DB_OF_SCRIPTS = (
    _output(
        "Devel::Cover's database",
        "cover_db",
        directories("cover_db"),
        "consider ignoring cover_db/",
        ("/cover_db/",),
        tied,
    )
    for tied in (BUILD_SYSTEMS, frozenset())
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

_PERL_VERSION = r"(5\.\d+(?:\.\d+)?|latest)"

PERL_ECOSYSTEM = Ecosystem(
    label="Perl",
    languages=PERL,
    build_systems=(MAKEMAKER, MODULE_BUILD, DIST_ZILLA, CPANFILE),
    source_suffixes={".pm": "Perl"},
    # `.pl` is Prolog's too and `.t` OCaml's cram tests; POD and XS files belong to a distribution without being Perl.
    ambiguous_suffixes={".pl": "Perl", ".t": "Perl", ".psgi": "Perl", ".pod": None, ".xs": None, ".PL": None},
    toolchain=toolchain_patterns(
        "Perl",
        version=_PERL_VERSION,
        inputs=("perl-version",),
        images=("perl",),
        more=(rf"\bperlbrew\s+(?:install|use|switch)\s+(?:perl-)?{_PERL_VERSION}",),
        # Devel::Cover's `cover` is a program of its own: `raco cover` and `go tool cover` are other languages'.
        programs=("perl", "prove", "cpanm", "cpm", "carton", "dzil", "perltidy", "perlcritic", "cover"),
        setup=("perl",),
    ),
)

PERL_VERSIONS = versions_axis("Perl version", "Perl", PERL)
