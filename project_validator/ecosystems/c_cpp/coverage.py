"""C and C++ coverage: gcovr, lcov, gcov and llvm-cov, and the compiler instrumentation for path coverage.

They move to the shared tools and toolchains once a second language uses them (Fortran; see docs/architecture.md).
"""

import re

from project_validator.build_configurations import option_values
from project_validator.core import Context
from project_validator.facts import Command, resolved
from project_validator.facts.coverage import CoverageTool, Granularity, Measurement, measured
from project_validator.facts.expansion import found_at, has_option, program, short_flags

C_AND_CXX = frozenset({"C", "C++"})
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


def _configuration_words(context: Context, path: str | None) -> tuple[str, ...]:
    """The options a gcovr.cfg (`key = value` lines) or .lcovrc gives, as words of a command line."""
    if path is None:
        return ()
    words: list[str] = []
    for line in context.project.read_text(path).splitlines():
        key, equals, value = line.partition("=")
        if equals and not key.lstrip().startswith("#"):
            words.extend((f"--{key.strip()}", value.strip()))
    return tuple(words)


def _gcovr(command: Command, context: Context) -> Measurement | None:
    argv = resolved(command)
    if program(argv) != "gcovr":
        return None
    named = option_values(argv, "--config")
    configuration = found_at(context, command.directory, named or ("gcovr.cfg",))
    words = (*argv, *_configuration_words(context, configuration))
    branch = (
        has_option(words, *_GCOVR_BRANCH_REPORTS)
        or "branch" in option_values(words, "--txt-metric")
        or bool(short_flags(argv) & {"b", "s", "x"})
    )
    return measured(LINE, BRANCH if branch else None, read=[configuration] if configuration else ())


_LCOV_PROGRAMS = frozenset({"lcov", "genhtml", "geninfo"})


def _rc_enabled(settings: list[str], *names: str) -> bool:
    return any(re.fullmatch(rf"(?:lcov_)?(?:{'|'.join(names)})\s*=\s*1", setting.strip()) for setting in settings)


def _lcov(command: Command, context: Context) -> Measurement | None:
    argv = resolved(command)
    if program(argv) not in _LCOV_PROGRAMS:
        return None
    named = option_values(argv, "--config-file")
    configuration = found_at(context, command.directory, named or (".lcovrc",))
    words = _configuration_words(context, configuration)
    settings = [
        *option_values(argv, "--rc"),
        *(f"{key[2:]}={value}" for key, value in zip(words[::2], words[1::2], strict=True)),
    ]
    branch = has_option(argv, "--branch-coverage") or _rc_enabled(settings, "branch_coverage")
    path = has_option(argv, "--mcdc-coverage") or _rc_enabled(settings, "mcdc_coverage")
    return measured(
        LINE, BRANCH if branch else None, PATH if path else None, read=[configuration] if configuration else ()
    )


def _gcov_options(argv: tuple[str, ...]) -> Measurement:
    letters = short_flags(argv)
    branch = bool(letters & {"b", "c"}) or has_option(argv, "--branch-probabilities", "--branch-counts")
    path = "g" in letters or has_option(argv, "--conditions") or any(word.startswith("--prime-paths") for word in argv)
    return measured(LINE, BRANCH if branch else None, PATH if path else None)


def _gcov(command: Command, _: Context) -> Measurement | None:
    argv = resolved(command)
    if re.fullmatch(r"(?:\w+-)*gcov(?:-\d+)?", program(argv)):
        return _gcov_options(argv)
    return None


_LLVM_COV = re.compile(r"llvm-cov(?:-\d+)?")


def _llvm_cov(command: Command, _: Context) -> Measurement | None:
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


def _cmake_configures(argv: tuple[str, ...]) -> bool:
    """Whether a cmake command configures a build tree, and so reads the CMake files."""
    excluded = ("--build", "--install", "-E", "-P", "--open", "--help", "--version")
    return program(argv) == "cmake" and not has_option(argv, *excluded)


def _instrumentation(flag: str) -> CoverageTool:
    """A compiler flag that instruments for path coverage: on a command line, in an environment variable a build
    reads, or in the CMake files a configuration reads."""
    found = re.compile(rf"(?<![\w-]){re.escape(flag)}\b")

    def measures(command: Command, context: Context) -> Measurement | None:
        argv = resolved(command)
        if any(found.search(word) for word in (*argv, *command.env.values())):
            return measured(PATH, heuristic=True)
        if _cmake_configures(argv) and any(found.search(text) for text in context.cmake_texts):
            return measured(PATH, read=context.project.cmake_files(), heuristic=True)
        return None

    name = f"{_COMPILERS[flag]} {flag}"
    return CoverageTool(name=name, languages=C_AND_CXX, can={PATH: name}, measures=measures)


_COMPILERS = {"-fcondition-coverage": "gcc", "-fpath-coverage": "gcc", "-fcoverage-mcdc": "clang"}

GCOVR = CoverageTool(
    name="gcovr",
    languages=C_AND_CXX,
    can={LINE: "gcovr", BRANCH: "gcovr --xml"},
    measures=_gcovr,
)
LCOV = CoverageTool(
    name="lcov",
    languages=C_AND_CXX,
    can={LINE: "lcov", BRANCH: "lcov --rc branch_coverage=1", PATH: "lcov --mcdc-coverage"},
    measures=_lcov,
)
GCOV = CoverageTool(
    name="gcov",
    languages=C_AND_CXX,
    can={LINE: "gcov", BRANCH: "gcov --branch-counts", PATH: "gcov --conditions"},
    measures=_gcov,
)
LLVM_COV = CoverageTool(
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
