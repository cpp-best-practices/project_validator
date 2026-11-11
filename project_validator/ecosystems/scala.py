"""Scala: built with sbt, Mill or scala-cli, judged by the JDK and Scala versions CI runs and by the tasks it runs.

The three tools run tasks: `sbt coverage test coverageReport` (several in one command, or in one quoted word with
`;`), `mill __.test` (a selector whose last segment is the task), `scala-cli test .`. Every tool here is one of those
tasks, so the tasks a command runs are read once (`sbt_tasks`, `mill_tasks`, `scala_cli_command`) and each tool asks
for its own. The JDK versions are the JVM profile's; a job that also names a Scala version (`sbt ++3.3.5 test`) runs
that version on each JDK it names."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directory_output
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Condition, Run, any_of, defined_by, either, when
from project_validator.text import Pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

SCALA = frozenset({"Scala"})

SBT_FILES = ("*.sbt",)
MILL_FILES = ("build.mill", "build.sc", "build.mill.scala")
SCALA_CLI_FILES = ("project.scala",)


def _output_beside(name: str, build_files: tuple[str, ...], *parents: str) -> Callable[[Path], bool]:
    """A directory called `name` next to one of `build_files`, or inside a directory called one of `parents` (sbt's
    `project/target`)."""

    def is_build_tree(directory: Path) -> bool:
        if directory.name != name:
            return False
        beside = any(next(directory.parent.glob(build_file), None) is not None for build_file in build_files)
        return beside or directory.parent.name in parents

    return is_build_tree


SBT = BuildSystem(
    name="sbt", files=SBT_FILES, languages=SCALA, is_build_tree=_output_beside("target", SBT_FILES, "project")
)
MILL = BuildSystem(name="Mill", files=MILL_FILES, languages=SCALA, is_build_tree=_output_beside("out", MILL_FILES))
SCALA_CLI = BuildSystem(
    name="scala-cli",
    files=SCALA_CLI_FILES,
    languages=SCALA,
    is_build_tree=_output_beside(".scala-build", SCALA_CLI_FILES),
)


# --- The tasks a command runs ---------------------------------------------------------------------------------------

# sbt options that take a value, so that the value is not taken for a task.
_SBT_VALUES = frozenset(
    {"--java-home", "-java-home", "-sbt-version", "--sbt-version", "-sbt-jar", "-sbt-dir", "-sbt-boot", "-ivy", "-mem"}
)
_SBT_PIECES = re.compile(r"[\s;]+")
_SCOPE = re.compile(r"^(?:[\w-]+/)+")


def sbt_tasks(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The tasks (and their options) an sbt command runs, in order: `sbt coverage test coverageReport`, or several in
    one quoted word (`sbt "scalafixAll --check"`, `sbt "; coverage; test"`). A scope is dropped (`core/test`,
    `Test/compile` are `test` and `compile`), so is a cross-building prefix (`+test` is `test`; `++3.3.5` switches the
    Scala version and is no task), and `project <name>` only selects a subproject."""
    if program(argv) not in ("sbt", "sbtn", "sbtx"):
        return ()
    words = iter(argv[1:])
    tasks: list[str] = []
    for word in words:
        if word in _SBT_VALUES:
            next(words, None)
            continue
        if word.startswith("-"):
            continue
        tasks.extend(piece for piece in _SBT_PIECES.split(word) if piece)
    found: list[str] = []
    pieces = iter(tasks)
    for piece in pieces:
        if piece == "project":
            next(pieces, None)
        elif piece.startswith("++"):
            continue
        elif piece.startswith("-"):
            found.append(piece)
        else:
            found.append(_SCOPE.sub("", piece.lstrip("+")))
    return tuple(found)


_MILL_VALUES = frozenset({"-j", "--jobs", "--color", "--ticker", "-D", "--define", "--import", "--meta-level"})


def mill_tasks(argv: tuple[str, ...]) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Each task a Mill command runs, as the segments of its selector and the arguments after it: `mill __.test` is
    `(("__", "test"), ())`; `mill __.fix --check + __.compile` two tasks. The words after a selector are its arguments
    until a `+` starts the next task."""
    if program(argv) != "mill":
        return ()
    words = iter(argv[1:])
    tasks: list[tuple[tuple[str, ...], list[str]]] = []
    expecting_task = True
    for word in words:
        if word in _MILL_VALUES:
            next(words, None)
        elif word == "+":
            expecting_task = True
        elif not expecting_task:
            tasks[-1][1].append(word)
        elif not word.startswith("-"):
            tasks.append((tuple(re.split(r"[./]", word)), []))
            expecting_task = False
    return tuple((segments, tuple(arguments)) for segments, arguments in tasks)


_SCALA_RUNNER_COMMANDS = frozenset({"test", "fmt", "compile", "run", "package", "doc", "fix"})


def scala_cli_command(argv: tuple[str, ...]) -> tuple[str, ...]:
    """A scala-cli (or `scala`, its runner since Scala 3.5) subcommand with its arguments: `scala-cli test .` is
    `("test", ".")`; `--power` before the subcommand is skipped."""
    name = program(argv)
    words = tuple(word for word in argv[1:] if word != "--power")
    if name == "scala-cli" or (name == "scala" and words[:1] and words[0] in _SCALA_RUNNER_COMMANDS):
        return words
    return ()


def sbt(*tasks: str, option: str | None = None) -> Condition:
    """Whether an sbt command runs one of `tasks` (given `option` somewhere after it, when named)."""

    def matches(command: Command) -> bool:
        found = sbt_tasks(resolved(command))
        return any(task in tasks for task in found) and (option is None or option in found)

    return matches


def mill(*tasks: str, option: str | None = None, within: str | None = None) -> Condition:
    """Whether a Mill command runs a selector ending in one of `tasks` (with `within` among its segments, and given
    `option`, when named)."""

    def matches(command: Command) -> bool:
        return any(
            segments[-1] in tasks
            and (within is None or within in segments[:-1])
            and (option is None or option in arguments)
            for segments, arguments in mill_tasks(resolved(command))
        )

    return matches


def scala_cli(*subcommands: str, option: str | None = None) -> Condition:
    def matches(command: Command) -> bool:
        words = scala_cli_command(resolved(command))
        return bool(words) and words[0] in subcommands and (option is None or option in words[1:])

    return matches


# --- Tests and coverage -------------------------------------------------------------------------------------------

SCALA_TEST_FILES = TestFiles(
    name="munit, ScalaTest, specs2, utest or ZIO Test suites under src/test/scala (or Mill's test/src)",
    languages=SCALA,
    path=re.compile(r"(?:^|/)(?:src/test/scala|test/src)/.+\.scala$"),
    contains=re.compile(
        r"^\s*import\s+(?:munit|org\.scalatest|org\.specs2|utest|zio\.test|org\.scalacheck|weaver|hedgehog)\b"
        r"|\bextends\s+(?:[\w.]+\.)?(?:FunSuite|ScalaCheckSuite|Any\w+Spec|\w+Spec|Specification|TestSuite|ZIOSpecDefault)\b",
        re.MULTILINE,
    ),
)

SBT_TEST = test_runner(
    name="sbt test",
    languages=SCALA,
    how="sbt test",
    runs=when(sbt("test", "testOnly", "testQuick"), tested),
    tests=tests_of(SCALA_TEST_FILES.name),
)
MILL_TEST = test_runner(
    name="mill __.test",
    languages=SCALA,
    how="mill __.test",
    runs=when(mill("test", "testOnly", "testCached"), tested),
    tests=tests_of(SCALA_TEST_FILES.name),
)
SCALA_CLI_TEST = test_runner(
    name="scala-cli test",
    languages=SCALA,
    how="scala-cli test .",
    runs=when(scala_cli("test"), tested),
    tests=tests_of(SCALA_TEST_FILES.name),
)

# scoverage instruments statements and branches; JaCoCo (sbt-jacoco) counts lines and branches.
SCOVERAGE = coverage_tool(
    name="scoverage",
    languages=SCALA,
    can={
        Granularity.STATEMENT: "sbt coverage test coverageReport (or mill __.scoverage.xmlReport)",
        Granularity.BRANCH: "sbt coverage test coverageReport (or mill __.scoverage.xmlReport)",
    },
    measures=when(
        any_of(
            sbt("coverageReport", "coverageAggregate"),
            mill("xmlReport", "htmlReport", "consoleReport", "xmlCoberturaReport", within="scoverage"),
        ),
        lambda: measured(Granularity.STATEMENT, Granularity.BRANCH),
    ),
)
SBT_JACOCO = coverage_tool(
    name="sbt-jacoco",
    languages=SCALA,
    can={Granularity.LINE: "sbt jacoco", Granularity.BRANCH: "sbt jacoco"},
    measures=when(
        sbt("jacoco", "jacocoReport", "jacocoAggregate"), lambda: measured(Granularity.LINE, Granularity.BRANCH)
    ),
)


# --- Formatting ---------------------------------------------------------------------------------------------------

SCALAFMT_SETTINGS = file_reader("scalafmt", (".scalafmt.conf",))


def _sbt_scalafmt(command: Command, facts: Facts) -> Run | None:
    """The sbt-scalafmt tasks: `scalafmtCheckAll`, `scalafmtCheck` and `scalafmtSbtCheck` fail on a file they would
    change; `scalafmtAll`, `scalafmt` and `scalafmtSbt` rewrite."""
    tasks = set(sbt_tasks(resolved(command)))
    if tasks & {"scalafmtCheckAll", "scalafmtCheck", "scalafmtSbtCheck"}:
        return formatted(command, facts, checks=True)
    if tasks & {"scalafmtAll", "scalafmt", "scalafmtSbt"}:
        return formatted(command, facts, checks=False)
    return None


def _mill_scalafmt(command: Command, facts: Facts) -> Run | None:
    """Mill's ScalafmtModule: `checkFormat` and `checkFormatAll` fail; `reformat` and `reformatAll` rewrite."""
    if mill("checkFormat", "checkFormatAll")(command):
        return formatted(command, facts, checks=True)
    if mill("reformat", "reformatAll")(command):
        return formatted(command, facts, checks=False)
    return None


def _scala_cli_fmt(command: Command, facts: Facts) -> Run | None:
    """`scala-cli fmt --check` fails on a file it would change; plain `scala-cli fmt` rewrites."""
    words = scala_cli_command(resolved(command))
    if not words or words[0] != "fmt":
        return None
    return formatted(command, facts, checks=bool({"--check", "--test"} & set(words)))


# scalafmt refuses to run without a `.scalafmt.conf` naming its version, so the style is never a default.
SCALAFMT = format_tool(
    name="scalafmt",
    languages=SCALA,
    can={
        Enforcement.CHECK: "sbt scalafmtCheckAll (or scalafmt --check, mill __.checkFormat, scala-cli fmt --check)",
        Enforcement.APPLY: "sbt scalafmtAll",
    },
    formats=either(
        flagged(("scalafmt",), checks=("--check", "--test", "--list")), _sbt_scalafmt, _mill_scalafmt, _scala_cli_fmt
    ),
    style=defined_by(files=(SCALAFMT_SETTINGS.name,), default=False),
)


# --- Warnings -----------------------------------------------------------------------------------------------------


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.MULTILINE))


# sbt-tpolecat sets the whole strict set (and, in its CI mode, fatal warnings).
_TPOLECAT = r"\bsbt-tpolecat\b|\btpolecat(?:ScalacOptions|DefaultOptionsMode|OptionsMode)\b"
DEPRECATION = _setting("-deprecation", rf"-deprecation\b|{_TPOLECAT}")
FEATURE = _setting("-feature", rf"-feature\b|{_TPOLECAT}")
LINT = _setting("-Xlint or -Wunused", rf"-Xlint\b|-Wunused\b|-Ywarn-unused\b|-Wall\b|{_TPOLECAT}")
SCALA_LINTS = (DEPRECATION, FEATURE, LINT)

FATAL_WARNINGS = _setting("-Werror", r"-Werror\b|-Xfatal-warnings\b")
TPOLECAT_CI_MODE = _setting("sbt-tpolecat's CI mode", r"\bSBT_TPOLECAT_CI\b|\bCiMode\b|\btpolecatCiMode\b")
_SCALA_WARNINGS_AS_ERRORS = (required(FATAL_WARNINGS), required(TPOLECAT_CI_MODE))

# Where scalac options are set: the sbt build (and `project/plugins.sbt`, which adds sbt-tpolecat), the Mill build,
# scala-cli's `//> using options` directives.
SCALA_COMPILER_OPTIONS = requirement_reader(
    "Scala compiler options",
    (*SBT_FILES, *MILL_FILES, *SCALA_CLI_FILES),
    (*(required(lint) for lint in SCALA_LINTS), *_SCALA_WARNINGS_AS_ERRORS),
)

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=SCALA,
    requirements=always(*(required(lint) for lint in SCALA_LINTS)),
    reads=(SCALA_COMPILER_OPTIONS.name,),
    words=Wording(
        kind="scalac warning options",
        hint="add -deprecation, -feature and -Xlint (Scala 2) or -Wunused:all (Scala 3) to scalacOptions, or use "
        "sbt-tpolecat, which sets them all",
        searched="the build or CI configuration",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=SCALA,
    requirements=always(*_SCALA_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(SCALA_COMPILER_OPTIONS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="the build or CI configuration",
        hint="add -Werror to scalacOptions, or run sbt-tpolecat in its CI mode (SBT_TPOLECAT_CI=true)",
    ),
)


# --- Analysis, security and audits -----------------------------------------------------------------------------------

SCALAFIX_SETTINGS = file_reader("scalafix", (".scalafix.conf",))

# scalafix runs the rules `.scalafix.conf` names; without it, none worth the name.
SCALAFIX = analyzer(
    name="scalafix",
    languages=SCALA,
    how='sbt "scalafixAll --check" (or mill __.fix --check)',
    analyses=when(any_of(sbt("scalafixAll", "scalafix"), mill("fix")), analysed),
    rules=defined_by(files=(SCALAFIX_SETTINGS.name,), default=False),
)

# CodeQL does not analyse Scala; semgrep and GitLab SAST do.
SECURITY_SCANNERS = tuple(tool for tool in multi_language_scanners(SCALA) if tool.name != "CodeQL")

# osv-scanner and trivy read no sbt build; snyk and GitLab Dependency Scanning do.
SBT_DEPENDENCY_CHECK = auditor(
    name="sbt-dependency-check",
    languages=SCALA,
    how="sbt dependencyCheck (OWASP dependency-check)",
    audits=when(sbt("dependencyCheck", "dependencyCheckAggregate", "dependencyCheckAnyProject"), audited),
)
AUDITORS = (
    SBT_DEPENDENCY_CHECK,
    *(tool for tool in multi_ecosystem_audits(SCALA) if tool.name in ("snyk", "GitLab Dependency Scanning")),
)

FUNCTION_LENGTH_LIMITERS = function_length_limiters(SCALA)


# --- Outputs -------------------------------------------------------------------------------------------------------


def _output(build_system: BuildSystem, directory: str, *more: str) -> BuildOutput:
    return directory_output(directory, languages=SCALA, build_systems=frozenset({build_system.name}), also=more)


SBT_TARGET = _output(SBT, "target", ".bsp/", ".bloop/", ".metals/")
MILL_OUT = _output(MILL, "out", ".bsp/")
SCALA_BUILD = _output(SCALA_CLI, ".scala-build", ".bsp/")


# --- Recognition and toolchains -----------------------------------------------------------------------------------

_SCALA_VERSION = r"(\d+\.\d+\.\d+(?:-\w+)?)"

SCALA_ECOSYSTEM = Ecosystem(
    label="Scala",
    languages=SCALA,
    build_systems=(SBT, MILL, SCALA_CLI),
    source_suffixes={".scala": "Scala"},
    # Scripts (Ammonite, Mill) are Scala once the project is; the sbt build definition names no language of its own.
    ambiguous_suffixes={".sc": "Scala", ".sbt": None},
    toolchain=toolchain_patterns(
        "Scala",
        version=_SCALA_VERSION,
        inputs=("scala-version",),
        more=(rf"\+\+{_SCALA_VERSION}", rf"--scala[=\s]+{_SCALA_VERSION}", rf"(?<![\w-])-S\s+{_SCALA_VERSION}"),
        commands=r"\bsbtn?\b|\bmill\b|\bscala-cli\b|\bscalac\b|\bcoursier/setup-action\b",
        setup=("sbt", "scala"),
    ),
)

# A Scala job without a version switch builds the version its build names: no version of its own.
_DEFAULT = "default"


def _scala_platforms(job: Job) -> frozenset[str]:
    """A job's toolchains: each Scala version it switches to (`++3.3.5`) on each JDK it names; the JDKs alone when it
    switches to none, or the Scala versions alone when it names no JDK."""
    scala = {f"Scala {version}" for version in toolchain_versions(job.toolchains, "Scala") if version != _DEFAULT}
    jdk = {f"JDK {version}" for version in toolchain_versions(job.toolchains, "JDK")}
    if scala and jdk:
        return frozenset(f"{runtime} / {language}" for runtime in sorted(jdk) for language in sorted(scala))
    return frozenset(scala | jdk) or toolchain_versions(job.toolchains, "Scala")


SCALA_VERSIONS = ToolchainAxis(languages=SCALA, noun="JDK or Scala version", of_job=_scala_platforms)
