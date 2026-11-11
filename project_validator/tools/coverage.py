"""Coverage of compiled languages: gcov and the reports built on it (gcovr, lcov), for what GCC compiles; llvm-cov,
for what Clang compiles (Swift's and Rust's coverage have their own tools, which know what their compilers measure);
and the compilers' instrumentation for path coverage."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from project_validator.build_systems.cmake.build import cmake_configures
from project_validator.facts import Command, Fact, Facts, Setting, resolved
from project_validator.facts.arguments import has_option, option_values, program, short_flags
from project_validator.facts.build import CompilerOption
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import joined
from project_validator.facts.settings import SettingsReader, key_value_settings
from project_validator.facts.tools import Run, Tool

C_AND_CXX = frozenset({"C", "C++"})
# The languages GCC's coverage instrumentation (--coverage) covers, which gcov reads.
GCC_LANGUAGES = C_AND_CXX | {"Fortran"}
LINE, REGION, BRANCH, PATH = Granularity.LINE, Granularity.REGION, Granularity.BRANCH, Granularity.PATH

# Every gcovr report but the default text report counts branches, as does its summary.
_GCOVR_BRANCH_REPORTS = (
    "--fail-under-branch",
    "--branches",
    "--print-summary",
    *(
        f"--{report}{style}"
        for report in ("xml", "cobertura", "json", "json-summary", "coveralls")
        for style in ("", "-pretty")
    ),
    "--sonarqube",
    "--jacoco",
    "--clover",
    "--lcov",
    "--html",
    "--html-details",
    "--html-nested",
)


def _named(programs: frozenset[str], option: str) -> Callable[[Command], list[str]]:
    """The configuration files a command of `programs` names with `option`, relative to the project."""

    def named(command: Command) -> list[str]:
        argv = resolved(command)
        return (
            [joined(command.directory, path) for path in option_values(argv, option)]
            if program(argv) in programs
            else []
        )

    return named


def _read_key_values(tool: str) -> Callable[[str, str], Iterable[Fact]]:
    def read(path: str, text: str) -> Iterable[Fact]:
        return key_value_settings(tool, path, text)

    return read


_GCOVR = frozenset({"gcovr"})
_LCOV_PROGRAMS = frozenset({"lcov", "genhtml", "geninfo"})
GCOVR_SETTINGS = SettingsReader(
    name="gcovr", files=("gcovr.cfg",), read=_read_key_values("gcovr"), named_by=_named(_GCOVR, "--config")
)
LCOV_SETTINGS = SettingsReader(
    name="lcov", files=(".lcovrc",), read=_read_key_values("lcov"), named_by=_named(_LCOV_PROGRAMS, "--config-file")
)


def _configuration(tool: str, command: Command, facts: Facts, named: list[str], default: str) -> tuple[Setting, ...]:
    """The settings of `tool` in the configuration file a command reads: the one it names, else `default` beside it."""
    return facts.settings(tool, paths=named[:1] or [joined(command.directory, default)])


def _gcovr(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) not in _GCOVR:
        return None
    read = _configuration("gcovr", command, facts, _named(_GCOVR, "--config")(command), "gcovr.cfg")
    words = (*argv, *(word for setting in read for word in (f"--{setting.key}", str(setting.value))))
    branch = (
        has_option(words, *_GCOVR_BRANCH_REPORTS)
        or "branch" in option_values(words, "--txt-metric")
        or bool(short_flags(argv) & {"b", "s", "x"})
    )
    return measured(LINE, BRANCH if branch else None, read=read)


def _rc_enabled(settings: list[str], *names: str) -> bool:
    return any(re.fullmatch(rf"(?:lcov_)?(?:{'|'.join(names)})\s*=\s*1", setting.strip()) for setting in settings)


def _lcov(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) not in _LCOV_PROGRAMS:
        return None
    read = _configuration("lcov", command, facts, _named(_LCOV_PROGRAMS, "--config-file")(command), ".lcovrc")
    settings = [*option_values(argv, "--rc"), *(f"{setting.key}={setting.value}" for setting in read)]
    branch = has_option(argv, "--branch-coverage") or _rc_enabled(settings, "branch_coverage")
    path = has_option(argv, "--mcdc-coverage") or _rc_enabled(settings, "mcdc_coverage")
    return measured(LINE, BRANCH if branch else None, PATH if path else None, read=read)


def _gcov_options(argv: tuple[str, ...]) -> Run:
    letters = short_flags(argv)
    branch = bool(letters & {"b", "c"}) or has_option(argv, "--branch-probabilities", "--branch-counts")
    path = "g" in letters or has_option(argv, "--conditions") or any(word.startswith("--prime-paths") for word in argv)
    return measured(LINE, BRANCH if branch else None, PATH if path else None)


def _gcov(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    if re.fullmatch(r"(?:\w+-)*gcov(?:-\d+)?", program(argv)):
        return _gcov_options(argv)
    return None


_LLVM_COV = re.compile(r"llvm-cov(?:-\d+)?")


def _llvm_cov(command: Command, _: Facts) -> Run | None:
    argv = resolved(command)
    if not _LLVM_COV.fullmatch(program(argv)) or len(argv) < 2:
        return None
    subcommand, options = argv[1], argv[1:]
    if subcommand == "gcov":
        return _gcov_options(options)
    if subcommand not in ("show", "report", "export"):
        return None
    # report and export count branches unless told not to; show shows them only when asked.
    hidden = any(re.fullmatch(r"--?show-branch-summary=(?:false|0)", word) for word in options)
    shown = has_option(options, "-show-branches", "--show-branches")
    branch = (subcommand != "show" and not hidden) or shown
    path = has_option(options, "-show-mcdc", "--show-mcdc", "-show-mcdc-summary", "--show-mcdc-summary")
    # Clang's source-based coverage counts regions too.
    return measured(LINE, REGION, BRANCH if branch else None, PATH if path else None)


def _instrumentation(flag: str) -> Tool:
    """A compiler flag that instruments for path coverage: on a command line, in an environment variable a build
    reads, or in the CMake files a configuration reads."""
    found = re.compile(rf"(?<![\w-]){re.escape(flag)}\b")

    def measures(command: Command, facts: Facts) -> Run | None:
        argv = resolved(command)
        if any(found.search(word) for word in (*argv, *command.env.values())):
            return measured(PATH, heuristic=True)
        if cmake_configures(argv) and (
            read := [option.origin.path for option in facts.where(CompilerOption, option=flag)]
        ):
            return measured(PATH, read=read)
        return None

    name = f"{_COMPILERS[flag]} {flag}"
    return coverage_tool(name=name, languages=C_AND_CXX, can={PATH: name}, measures=measures, reads=("CMake",))


_COMPILERS = {"-fcondition-coverage": "gcc", "-fpath-coverage": "gcc", "-fcoverage-mcdc": "clang"}

GCOVR = coverage_tool(
    name="gcovr",
    languages=GCC_LANGUAGES,
    can={LINE: "gcovr", BRANCH: "gcovr --xml"},
    measures=_gcovr,
    reads=("gcovr",),
)
LCOV = coverage_tool(
    name="lcov",
    languages=GCC_LANGUAGES,
    can={LINE: "lcov", BRANCH: "lcov --rc branch_coverage=1", PATH: "lcov --mcdc-coverage"},
    measures=_lcov,
    reads=("lcov",),
)
GCOV = coverage_tool(
    name="gcov",
    languages=GCC_LANGUAGES,
    can={LINE: "gcov", BRANCH: "gcov --branch-counts", PATH: "gcov --conditions"},
    measures=_gcov,
)
LLVM_COV = coverage_tool(
    name="llvm-cov",
    languages=C_AND_CXX,
    can={
        LINE: "llvm-cov report",
        REGION: "llvm-cov report",
        BRANCH: "llvm-cov report",
        PATH: "llvm-cov show -show-mcdc",
    },
    measures=_llvm_cov,
)
GCC_CONDITION_COVERAGE = _instrumentation("-fcondition-coverage")
GCC_PATH_COVERAGE = _instrumentation("-fpath-coverage")
CLANG_MCDC = _instrumentation("-fcoverage-mcdc")

COVERAGE_TOOLS = (GCOVR, LCOV, GCOV, LLVM_COV, GCC_CONDITION_COVERAGE, GCC_PATH_COVERAGE, CLANG_MCDC)
