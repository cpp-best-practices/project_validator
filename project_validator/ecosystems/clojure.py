"""Clojure (and ClojureScript): built with the Clojure CLI (`deps.edn`), Leiningen (`project.clj`), Babashka (`bb.edn`)
or shadow-cljs, judged by the JDK versions CI runs (the JVM profile's) and by the tools it runs on the code: the test
runners, cloverage, clj-kondo, cljfmt and its kin, and nvd-clojure.

The Clojure CLI runs aliases: `clojure -M:test`, `clojure -X:test`, `clojure -T:build test`. A tool is known by its
alias when it is the alias's name (`:test`, `:kaocha`, `:cloverage`), and by its program when CI runs it directly."""

from __future__ import annotations

import re
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, either, starts, when
from project_validator.text import pattern
from project_validator.tools.scanners import multi_language_scanners

CLOJURE = frozenset({"Clojure"})
DEPS_EDN = "deps.edn"
PROJECT_CLJ = "project.clj"


def _is_build_tree(directory: Path) -> bool:
    """The CLI's classpath cache, Leiningen's (and tools.build's) `target`, shadow-cljs's cache."""
    if directory.name in (".cpcache", ".shadow-cljs"):
        return True
    return directory.name == "target" and any((directory.parent / name).is_file() for name in (DEPS_EDN, PROJECT_CLJ))


CLOJURE_CLI = BuildSystem(name="Clojure CLI", files=(DEPS_EDN,), languages=CLOJURE, is_build_tree=_is_build_tree)
LEININGEN = BuildSystem(name="Leiningen", files=(PROJECT_CLJ,), languages=CLOJURE, is_build_tree=_is_build_tree)
BABASHKA = BuildSystem(name="Babashka", files=("bb.edn",), languages=CLOJURE)
SHADOW_CLJS = BuildSystem(
    name="shadow-cljs", files=("shadow-cljs.edn",), languages=CLOJURE, is_build_tree=_is_build_tree
)
BUILD_SYSTEMS = frozenset({CLOJURE_CLI.name, LEININGEN.name, BABASHKA.name, SHADOW_CLJS.name})

_ALIAS = re.compile(r"^-[MXTA]:(?P<names>[\w.:-]+)$")


def cli_aliases(argv: tuple[str, ...]) -> frozenset[str]:
    """The aliases a Clojure CLI command runs (`clojure -M:test:dev` runs `test` and `dev`); none for another
    command."""
    if program(argv) not in ("clojure", "clj"):
        return frozenset()
    found = (match["names"].split(":") for word in argv[1:] if (match := _ALIAS.match(word)))
    return frozenset(name for names in found for name in names if name)


def _alias_matches(command: Command, regex: re.Pattern[str]) -> bool:
    return any(regex.search(alias) for alias in cli_aliases(resolved(command)))


# --- Tests and coverage ---------------------------------------------------------------------------------------------

CLOJURE_TEST_FILES = TestFiles(
    name="deftest (clojure.test) or describe (speclj) under test/",
    languages=CLOJURE,
    path=re.compile(r"(?:^|/)(?:test|spec)/.+\.clj[sc]?$|_(?:test|spec)\.clj[sc]?$"),
    contains=re.compile(r"\((?:t/|clojure\.test/|ct/)?deftest\s|\(defspec\s|\(describe\s+\"|\(deftest-\w+\s"),
)
_TEST_ALIAS = re.compile(r"test|kaocha|cloverage|coverage|cov|eftest|spec")
_TEST_RUNNERS = (
    ("lein", "test"),
    ("lein", "kaocha"),
    ("lein", "cloverage"),
    ("lein", "eftest"),
    ("lein", "spec"),
    ("bb", "test"),
    ("kaocha",),
    ("bin/kaocha",),
    ("shadow-cljs", "compile", "test"),
    ("npx", "shadow-cljs", "compile", "test"),
)


def _runs_tests(command: Command) -> bool:
    argv = resolved(command)
    if starts_with(argv, *_TEST_RUNNERS) is not None or program(argv) == "kaocha":
        return True
    return _alias_matches(command, _TEST_ALIAS)


CLOJURE_TEST = test_runner(
    name="clojure.test",
    languages=CLOJURE,
    how="clojure -M:test (or -X:test, lein test, kaocha, bb test)",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(CLOJURE_TEST_FILES.name),
)

_CLOVERAGE_ALIAS = re.compile(r"cloverage|coverage|^cov$")


def _cloverage(command: Command, _facts: Facts) -> Run | None:
    """cloverage counts the forms (and lines) the tests run: `lein cloverage`, or the CLI alias that runs it."""
    argv = resolved(command)
    if "cloverage" in argv or _alias_matches(command, _CLOVERAGE_ALIAS):
        return measured(Granularity.STATEMENT)
    return None


CLOVERAGE = coverage_tool(
    name="cloverage",
    languages=CLOJURE,
    can={Granularity.STATEMENT: "lein cloverage (or clojure -M:coverage, an alias running cloverage): form coverage"},
    measures=_cloverage,
)


# --- Formatting -----------------------------------------------------------------------------------------------------


def _cli_formatter(name: str, command: Command, facts: Facts) -> Run | None:
    """A formatter run through its CLI alias (`clojure -M:cljfmt check`): the word after the alias says what."""
    argv = resolved(command)
    if not any(alias == name for alias in cli_aliases(argv)):
        return None
    words = [word for word in argv[1:] if not word.startswith("-")]
    if "check" in words:
        return formatted(command, facts, checks=True)
    return formatted(command, facts, checks=False) if "fix" in words else None


# cljfmt (`cljfmt check`/`fix`, `lein cljfmt check`), cljstyle (`cljstyle check`/`fix`) and zprint (`-c`/`--check`
# checks, `-w`/`--write` rewrites) all have a default style; `.cljfmt.edn`, `.cljstyle` and `.zprintrc` pick another.
CLJFMT_SETTINGS = file_reader("cljfmt", (".cljfmt.edn", ".cljfmt.clj", "cljfmt.edn"))
CLJFMT = format_tool(
    name="cljfmt",
    languages=CLOJURE,
    can={Enforcement.CHECK: "cljfmt check (or lein cljfmt check)", Enforcement.APPLY: "cljfmt fix"},
    formats=either(
        flagged(("cljfmt",), ("lein", "cljfmt"), checks=("check",), applies=("fix",)),
        lambda command, facts: _cli_formatter("cljfmt", command, facts),
    ),
    style=defined_by(files=(CLJFMT_SETTINGS.name,)),
)
CLJSTYLE = format_tool(
    name="cljstyle",
    languages=CLOJURE,
    can={Enforcement.CHECK: "cljstyle check", Enforcement.APPLY: "cljstyle fix"},
    formats=flagged(("cljstyle",), checks=("check",), applies=("fix",)),
    style=defined_by(named=(".cljstyle",)),
)
ZPRINT = format_tool(
    name="zprint",
    languages=CLOJURE,
    can={Enforcement.CHECK: "zprint --check src/**/*.clj", Enforcement.APPLY: "zprint --write src/**/*.clj"},
    formats=flagged(("zprint",), checks=("-c", "--check"), applies=("-w", "--write")),
    style=defined_by(named=(".zprintrc", ".zprint.edn")),
)


# --- Lints and warnings ---------------------------------------------------------------------------------------------

# clj-kondo's lints stand in for compiler warnings (the compiler has one, reflection, which `*warn-on-reflection*`
# turns on). clj-kondo exits non-zero on a warning unless told `--fail-level error`; installing it (setup-clj-kondo, or
# setup-clojure's `clj-kondo:` input) is not running it.
_KONDO = r"(?<![\w/-])clj-kondo\b(?![\w-]*:)"
CLJ_KONDO = pattern("clj-kondo", rf"{_KONDO}|\blein\s+clj-kondo\b|-[MX]:clj-kondo\b")
KONDO_FAILS = pattern(
    "clj-kondo failing on warnings",
    rf"(?:{_KONDO}|\blein\s+clj-kondo\b|-[MX]:clj-kondo\b)(?![^\n]*--fail-level\s+error)",
)
WARN_ON_REFLECTION = pattern(
    "*warn-on-reflection*",
    r"\*warn-on-reflection\*\s+true\b|\(set!\s+\*warn-on-reflection\*\s+true\)|\*warn-on-reflection\*=true",
)
CLOJURE_SETTINGS = requirement_reader(
    "Clojure build settings", (DEPS_EDN, PROJECT_CLJ, "*.clj", "*.cljc"), (required(WARN_ON_REFLECTION),)
)
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=CLOJURE,
    requirements=always(required(CLJ_KONDO, in_files=False), required(WARN_ON_REFLECTION)),
    reads=(CLOJURE_SETTINGS.name,),
    words=Wording(
        kind="Clojure lints",
        searched="CI configuration, the build files and the sources",
        hint="run clj-kondo --lint src test in CI and set *warn-on-reflection* (:global-vars in project.clj, or "
        "(set! *warn-on-reflection* true) in the namespaces)",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=CLOJURE,
    requirements=always(required(KONDO_FAILS, in_files=False)),
    any_one=True,
    words=Wording(
        kind="warnings as errors",
        hint="run clj-kondo in CI without --fail-level error, so that a warning fails the job (its default)",
    ),
)

CLJ_KONDO_SETTINGS = file_reader("clj-kondo", (".clj-kondo/config.edn",))
CLJ_KONDO_ANALYZER = analyzer(
    name="clj-kondo",
    languages=CLOJURE,
    how="clj-kondo --lint src test",
    analyses=when(lambda command: CLJ_KONDO.regex.search(" ".join(resolved(command))) is not None, analysed),
    rules=defined_by(files=(CLJ_KONDO_SETTINGS.name,)),
)

# semgrep reads Clojure; CodeQL and GitLab SAST do not.
SECURITY_SCANNERS = tuple(tool for tool in multi_language_scanners(CLOJURE) if tool.name == "semgrep")

# nvd-clojure (OWASP dependency-check over the classpath) and clj-watson audit the dependencies.
_NVD_ALIAS = re.compile(r"^nvd(?:-clojure)?$")
DEPENDENCY_AUDITORS = (
    auditor(
        name="nvd-clojure",
        languages=CLOJURE,
        how="clojure -M:nvd (or lein nvd check)",
        audits=lambda command, _facts: (
            audited() if starts(("lein", "nvd"))(command) or _alias_matches(command, _NVD_ALIAS) else None
        ),
    ),
    auditor(
        name="clj-watson",
        languages=CLOJURE,
        how="clj-watson scan -p deps.edn",
        audits=when(starts(("clj-watson",)), audited),
    ),
)


# --- Outputs --------------------------------------------------------------------------------------------------------


def _directory(name: str, hint: str, *, written_by: frozenset[str]) -> BuildOutput:
    """A directory the build systems `written_by` write at the top of the project (none: the language's own)."""
    return BuildOutput(
        languages=CLOJURE,
        build_systems=written_by,
        name=f"the {name} directory",
        globs=ignored_at_top_level(re.escape(name)),
        paths=directories(name),
        hint=hint,
        artifacts=(f"/{name}/",),
    )


CLASSPATH_CACHE = _directory(".cpcache", "consider ignoring .cpcache/", written_by=frozenset({CLOJURE_CLI.name}))
TARGET_DIRECTORY = _directory(
    "target", "consider ignoring target/", written_by=frozenset({CLOJURE_CLI.name, LEININGEN.name})
)
SHADOW_CACHE = _directory(".shadow-cljs", "consider ignoring .shadow-cljs/", written_by=frozenset({SHADOW_CLJS.name}))
# The REPL's port file, for projects of any build system and for plain sources alike (an output tied to a used build
# system hides the language-wide ones).
NREPL_PORT, NREPL_PORT_OF_SOURCES = (
    BuildOutput(
        languages=CLOJURE,
        build_systems=tied,
        name="the .nrepl-port file",
        globs=ignored_at_top_level(r"\.nrepl-port"),
        paths=(".nrepl-port",),
        hint="consider ignoring .nrepl-port",
        artifacts=(".nrepl-port",),
    )
    for tied in (BUILD_SYSTEMS, frozenset())
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# Clojure runs on the JDK the JVM profile recognises; the Clojure version is the dependency deps.edn names, not a CI
# toolchain. A job shows it runs Clojure by its tools.
CLOJURE_ECOSYSTEM = Ecosystem(
    label="Clojure",
    languages=CLOJURE,
    build_systems=(CLOJURE_CLI, LEININGEN, BABASHKA, SHADOW_CLJS),
    source_suffixes={".clj": "Clojure", ".cljs": "Clojure", ".cljc": "Clojure"},
    # EDN data is a file of the ecosystem with no language of its own; Babashka scripts are Clojure.
    ambiguous_suffixes={".edn": None, ".bb": "Clojure"},
    toolchain=toolchain_patterns(
        "Clojure",
        commands=r"\bclojure\b|\bclj\s+-|\blein\b|\bbb\s+(?:test|run|tasks?)\b|\bkaocha\b|\bclj-kondo\b|\bcljfmt\b"
        r"|\bcljstyle\b|\bzprint\b|\bshadow-cljs\b|\bclj-watson\b",
        setup=("clojure",),
    ),
)


def _clojure_platforms(job: Job) -> frozenset[str]:
    """A Clojure job's toolchains: the JDKs it names; its runner's default JDK when it names none."""
    return toolchain_versions(job.toolchains, "JDK") or toolchain_versions(job.toolchains, "Clojure")


JDK_VERSIONS_FOR_CLOJURE = ToolchainAxis(languages=CLOJURE, noun="JDK version", of_job=_clojure_platforms)
