"""Fortran: built with CMake, Meson or fpm (the Fortran Package Manager), judged by its compilers (gfortran, Intel's
ifx and ifort, LLVM's flang).

Everything else Fortran shares: CMake's and Meson's facts (which already scope options by language and compiler), the
test runners ctest and `meson test`, gcov and the reports built on it, lizard. What this profile adds is recognition,
fpm, and the Fortran compilers' flags for the practices.
"""

import re
from collections.abc import Iterator

from project_validator.build_configurations import build_type_kinds
from project_validator.build_systems.cmake.build import CMAKE
from project_validator.build_systems.meson.build import MESON
from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem
from project_validator.facts import Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, option_values, program
from project_validator.facts.axes import ToolchainAxis
from project_validator.facts.build import BuildSetting
from project_validator.facts.dependencies import Lock, PackageManager, manifest_reader
from project_validator.facts.flags import flag_requirement
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import EXTENSIONS, Evidence, Found, Practice, Requirement
from project_validator.facts.practices import HARDENING as HARDENING_PRACTICE
from project_validator.facts.practices import WARNINGS as WARNINGS_PRACTICE
from project_validator.facts.practices import WARNINGS_AS_ERRORS as WARNINGS_AS_ERRORS_PRACTICE
from project_validator.facts.settings import SettingsReader, toml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Definition, Run, defined_by, starts, when
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.toolchains import (
    FHARDENED,
    GCC_HARDENING,
    WARNING_LEVEL_HINTS,
    WARNINGS_AS_ERRORS_SETTING_HINTS,
    WARNINGS_AS_ERRORS_SETTINGS,
    Flag,
    warning_level_settings,
)

FORTRAN = "Fortran"
FORTRAN_LANGUAGE = frozenset({FORTRAN})

# --- fpm

FPM_MANIFEST = "fpm.toml"
# The fpm commands that build, and the profile each builds when given none.
_FPM_BUILDS = frozenset({"build", "test", "run", "install"})


def _fpm_command(argv: tuple[str, ...]) -> str | None:
    """The fpm subcommand that builds, or None."""
    return argv[1] if program(argv) == "fpm" and argv[1:2] and argv[1] in _FPM_BUILDS else None


def _fpm_profile(argv: tuple[str, ...]) -> str:
    return next(iter(option_values(argv, "--profile")), "debug")


def fpm_build_types(command: Command) -> frozenset[str]:
    """The build type an fpm command builds: its `--profile`, debug by default."""
    argv = resolved(command)
    return build_type_kinds(_fpm_profile(argv)) if _fpm_command(argv) else frozenset()


FPM = BuildSystem(
    name="fpm",
    files=(FPM_MANIFEST,),
    languages=FORTRAN_LANGUAGE,
    build_types=fpm_build_types,
)
FPM_SETTINGS = SettingsReader(
    name="fpm", files=(FPM_MANIFEST,), read=lambda path, text: toml_settings("fpm", path, text)
)

# The flags fpm's built-in profiles pass each compiler, when a command gives no flags of its own (`--flag`, or the
# FPM_FFLAGS environment variable; with a `--profile`, those are added to the profile's).
_FPM_PROFILE_FLAGS = {
    ("debug", "gcc"): (
        *("-Wall", "-Wextra", "-Wimplicit-interface", "-Wno-unused-dummy-argument", "-fPIC", "-fmax-errors=1"),
        *("-g", "-fcheck=bounds", "-fcheck=array-temps", "-fbacktrace", "-fcoarray=single"),
    ),
    ("release", "gcc"): ("-O3", "-Wimplicit-interface", "-fPIC", "-fmax-errors=1", "-funroll-loops"),
    ("debug", "intel"): ("-warn all", "-check all", "-error-limit 1", "-O0", "-g", "-assume byterecl", "-traceback"),
    ("release", "intel"): ("-fp-model precise", "-pc64", "-align all", "-error-limit 1", "-reentrancy threaded"),
}


def _fpm_flags(command: Command, compiler: str) -> tuple[str, ...]:
    """The flags of its profile an fpm command passes `compiler`."""
    argv = resolved(command)
    if _fpm_command(argv) is None:
        return ()
    profile = option_values(argv, "--profile")
    if not profile and (has_option(argv, "--flag") or "FPM_FFLAGS" in command.env):
        return ()
    return _FPM_PROFILE_FLAGS.get((profile[0] if profile else "debug", compiler), ())


def _fpm_test(command: Command, _facts: Facts) -> Run | None:
    return tested() if _fpm_command(resolved(command)) == "test" else None


# A test program or module in a test directory (fpm's `test/`, and the conventional `tests/`), or a pFUnit test.
FORTRAN_TEST_FILES = TestFiles(
    name="Fortran test programs in test/",
    languages=FORTRAN_LANGUAGE,
    path=re.compile(r"(?:^|/)tests?/(?:.*/)?[^/]+\.(?:[fF](?:90|95|03|08|18)?|pf|fypp)$"),
    contains=re.compile(r"^\s*(?:program|module|submodule)\b|^\s*@test\b", re.MULTILINE | re.IGNORECASE),
)
FPM_TEST = test_runner(
    name="fpm test",
    languages=FORTRAN_LANGUAGE,
    how="fpm test",
    runs=_fpm_test,
    tests=tests_of(FORTRAN_TEST_FILES.name),
)

FPM_MANIFESTS = manifest_reader(
    name="fpm dependencies",
    manager="fpm",
    files=(FPM_MANIFEST,),
    declares=lambda _path, text: bool(re.search(r"^\s*\[(?:dev-)?dependencies\]", text, re.MULTILINE)),
)
# fpm has no lockfile: a dependency is pinned by its `tag` or `rev`.
FPM_MANAGER = PackageManager(name="fpm", languages=FORTRAN_LANGUAGE, lock=Lock.NEVER, suggested=True)

# --- compilers

# The compilers that compile Fortran, by the family CI and the build systems name them by.
FORTRAN_COMPILERS = frozenset({"gcc", "intel", "flang"})
# What shows a CI job builds Fortran.
CI_USAGE = re.compile(
    r"\bgfortran\b|\bifx\b|\bifort\b|\b(?:llvm-)?flang(?:-new)?\b|\blfortran\b|\bfpm\b|\bsetup-fortran\b"
    r"|\.[fF](?:90|95|03|08)\b"
)


def builds_fortran(job: Job) -> bool:
    """A job builds Fortran when it is seen doing so, or building with the tools Fortran shares with C and C++."""
    return not job.ecosystems or bool({FORTRAN, "C/C++"} & job.ecosystems)


def _compilers(job: Job) -> frozenset[str]:
    return job.compilers & FORTRAN_COMPILERS if builds_fortran(job) else frozenset()


def _uses_runner_default_compiler(job: Job) -> bool:
    return job.default_compiler and builds_fortran(job)


FORTRAN_COMPILERS_AXIS = ToolchainAxis(
    languages=FORTRAN_LANGUAGE,
    noun="compiler",
    of_job=_compilers,
    runner_default=_uses_runner_default_compiler,
    compiled=True,
)


def ci_compilers(facts: Facts) -> tuple[str, ...]:
    """The Fortran compilers CI builds with; gfortran's flags are asked for when CI names none."""
    found = {compiler for job in facts.of(Job) for compiler in _compilers(job)}
    return tuple(sorted(found)) or ("gcc",)


GFORTRAN_WARNINGS = (
    Flag("-Wall", "-Wall"),
    Flag("-Wextra", "-Wextra"),
    Flag("-Wpedantic", "-Wpedantic|-pedantic(?:-errors)?"),
    Flag("-Wimplicit-interface", "-Wimplicit-interface"),
)
_WARNINGS = {
    "gcc": GFORTRAN_WARNINGS,
    "intel": (Flag("-warn all", r"-warn[\s:]all|/warn:all"),),
    "flang": (Flag("-pedantic", "-pedantic|-Wpedantic"),),
}
_ERRORS = {
    "gcc": Flag("-Werror", "-Werror"),
    "intel": Flag("-warn errors", r"-warn[\s:]errors|/warn:errors"),
    "flang": Flag("-Werror", "-Werror"),
}
# A standard, not the GNU or legacy dialect.
_STANDARDS = {
    "gcc": Flag("-std=f2018", r"-std=f(?:95|2003|2008|2018|2023)"),
    "intel": Flag("-stand f18", r"-stand[\s:]f(?:95|03|08|18|23)|/stand:f(?:95|03|08|18|23)"),
    "flang": Flag("-std=f2018", r"-std=f(?:95|2003|2008|2018|2023)"),
}
# The stack and control-flow protections GCC's (and so gfortran's) back end adds; library-call checks and assertions
# are C's and C++'s. Intel's LLVM-based ifx takes the first two.
_PROTECTIONS = ("-fstack-protector-strong", "-fcf-protection", "-fstack-clash-protection")
_GFORTRAN_HARDENING = tuple(
    Flag(flag.name, f"{flag.spellings}|{FHARDENED}", (*flag.hints, FHARDENED))
    for flag in GCC_HARDENING
    if flag.name in _PROTECTIONS
)
_HARDENING = {
    "gcc": _GFORTRAN_HARDENING,
    "intel": tuple(flag for flag in GCC_HARDENING if flag.name in _PROTECTIONS[:2]),
}


def _fpm_profile_flags(flag: Flag) -> Found:
    """The flags of the fpm profile a CI command builds with that set `flag` for the compiler judged."""

    def found(facts: Facts, compiler: str | None) -> Iterator[Evidence]:
        for command in facts.of(Command):
            if any(flag.option.fullmatch(word) for word in _fpm_flags(command, compiler or "gcc")):
                yield Evidence(f"{command.origin.path} (fpm's {_fpm_profile(resolved(command))} profile)")

    return found


def _flag(flag: Flag, configured: tuple[str, ...] = (), hints: tuple[str, ...] = ()) -> Requirement:
    """A flag for Fortran builds: on a command line, in the build files, or in the fpm profile a command builds
    with; `configured` are the build system settings a command line sets it with, found by `hints`."""
    return flag_requirement(
        flag, FORTRAN_LANGUAGE, configured=configured, configured_hints=hints, also=(_fpm_profile_flags(flag),)
    )


BUILD_FILES = ("CMake", "Meson")


def _warnings(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return tuple(
        _flag(flag, warning_level_settings(flag), WARNING_LEVEL_HINTS) for flag in _WARNINGS.get(compiler or "gcc", ())
    )


def _errors(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    flag = _ERRORS.get(compiler or "gcc")
    return () if flag is None else (_flag(flag, WARNINGS_AS_ERRORS_SETTINGS, WARNINGS_AS_ERRORS_SETTING_HINTS),)


WARNINGS = Practice(
    name=WARNINGS_PRACTICE,
    languages=FORTRAN_LANGUAGE,
    kind="Fortran compiler warning flags",
    requirements=_warnings,
    reads=BUILD_FILES,
    separator=" ",
    hint="enable -Wall -Wextra -Wpedantic -Wimplicit-interface (ifx: -warn all) for each compiler CI uses",
    compilers=ci_compilers,
)
WARNINGS_AS_ERRORS = Practice(
    name=WARNINGS_AS_ERRORS_PRACTICE,
    languages=FORTRAN_LANGUAGE,
    kind="warnings as errors",
    requirements=_errors,
    any_one=True,
    reads=BUILD_FILES,
    searched="CI configuration or the build files (CMake files, presets, meson.build, fpm flags)",
    hint="add -Werror (gfortran, flang), -warn errors (ifx) or set CMAKE_COMPILE_WARNING_AS_ERROR (Meson: "
    "werror=true), at least as an option",
    compilers=ci_compilers,
)


def _standard(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    flag = _STANDARDS.get(compiler or "gcc")
    meson = Requirement(
        name="fortran_std=f2018",
        runs=re.compile(r"(?<![\w-])(?:-D\s*)?fortran_std\s*=\s*f\d+\b"),
        found=_meson_standard,
    )
    return (meson,) if flag is None else (_flag(flag), meson)


def _meson_standard(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
    for setting in facts.where(BuildSetting, build_system="Meson", name="fortran_std"):
        if re.fullmatch(r"f\d+", setting.value):
            yield Evidence(setting.origin.path, setting.applies.requires)


EXTENSIONS_PRACTICE = Practice(
    name=EXTENSIONS,
    languages=FORTRAN_LANGUAGE,
    kind="Fortran standard settings",
    requirements=_standard,
    any_one=True,
    reads=BUILD_FILES,
    hint="compile to a standard: -std=f2018 (ifx: -stand f18; Meson: default_options: ['fortran_std=f2018'])",
    passed="Fortran is compiled to a standard, without the compilers' extensions, with {found}",
    failed="Fortran is never compiled to a standard; the compilers' extensions are allowed",
    question="whether Fortran is compiled to a standard",
    compilers=ci_compilers,
)


def _hardening(_facts: Facts, compiler: str | None) -> tuple[Requirement, ...]:
    return tuple(_flag(flag) for flag in _HARDENING.get(compiler or "gcc", ()))


PROGRAM = re.compile(r"^\s*program\s+\w", re.MULTILINE | re.IGNORECASE)


def _read_programs(context: Context) -> Iterator[Fact]:
    """Whether a Fortran program is built, outside the tests: a library has no binary to harden."""
    project = context.project
    sources = (
        path for path in project.files() if FORTRAN_SOURCE.search(path) and not FORTRAN_TEST_FILES.path.search(path)
    )
    program = next((path for path in sources if PROGRAM.search(project.read_text(path))), None)
    if program is not None:
        yield Setting(origin=Origin(path=program), tool="Fortran programs", key="program", value=True)


# Read in a project with a build file Fortran is built with.
FORTRAN_PROGRAMS = SettingsReader(
    name="Fortran programs",
    files=(FPM_MANIFEST, "CMakeLists.txt", "meson.build", "Makefile", "makefile", "GNUmakefile"),
    read_project=_read_programs,
)


def _no_program(facts: Facts) -> str | None:
    if facts.where(Setting, tool="Fortran programs"):
        return None
    return "no Fortran program is built; a library has no binary"


HARDENING = Practice(
    name=HARDENING_PRACTICE,
    languages=FORTRAN_LANGUAGE,
    kind="hardening options",
    requirements=_hardening,
    reads=BUILD_FILES,
    hint=f"enable {FHARDENED} (GCC 14+) or {', '.join(_PROTECTIONS)}",
    compilers=ci_compilers,
    skipped=_no_program,
)

# --- tools

FPRETTIFY = format_tool(
    name="fprettify",
    languages=FORTRAN_LANGUAGE,
    can={Enforcement.CHECK: "fprettify --diff --recursive .", Enforcement.APPLY: "fprettify --recursive ."},
    formats=flagged(("fprettify",), checks=("--diff", "-d", "--stdout", "-s")),
    style=defined_by(named=(".fprettify.rc",)),
)


_fortitude = when(starts(("fortitude", "check")), analysed)


FORTITUDE_SETTINGS = SettingsReader(
    name="fortitude",
    files=("fortitude.toml", ".fortitude.toml", FPM_MANIFEST),
    read=lambda path, text: toml_settings(
        "fortitude", path, text, *(("extra", "fortitude") if path.endswith(FPM_MANIFEST) else ())
    ),
)
FORTITUDE = analyzer(
    name="fortitude",
    languages=FORTRAN_LANGUAGE,
    how="fortitude check",
    analyses=_fortitude,
    rules=Definition(found=lambda _facts: (), default=True),
    reads=("fortitude",),
)
FUNCTION_LENGTH_LIMITERS = function_length_limiters(FORTRAN_LANGUAGE)

BUILD_OUTPUTS = BuildOutput(
    languages=FORTRAN_LANGUAGE,
    name="the build directory and module files",
    globs=ignored_at_top_level(r"_?build(?:[-_*][\w*-]*)?|\*\.mod|\*\.smod"),
    paths=directories("build", "_build"),
    hint="consider ignoring the build directory (fpm and CMake build in build/) and compiled module files (*.mod)",
    artifacts=("*.o", "*.obj", "*.a", "*.so", "*.dll", "*.exe", "*.mod", "*.smod", "/build/"),
    # Go's module file, in a project that has Go too.
    not_artifacts=("go.mod",),
)

# --- recognition

# Fixed form (.f, .for), free form (.f90 and the later standards' suffixes), and preprocessed sources (.F90, .fpp, and
# fypp templates).
FORTRAN_SUFFIXES = (
    *(f".{form}" for form in ("f", "F", "for", "FOR", "ftn", "FTN", "f77", "F77", "fpp", "FPP", "fypp")),
    *(f".{f}{standard}" for f in ("f", "F") for standard in ("90", "95", "03", "08", "18")),
)
FORTRAN_SOURCE = re.compile(rf"(?:{'|'.join(map(re.escape, FORTRAN_SUFFIXES))})$")

FORTRAN_ECOSYSTEM = Ecosystem(
    label=FORTRAN,
    languages=FORTRAN_LANGUAGE,
    build_systems=(CMAKE, MESON, FPM),
    default_build_system=FPM,
    ci_usage=CI_USAGE,
    source_suffixes=dict.fromkeys(FORTRAN_SUFFIXES, FORTRAN),
    # pFUnit's test files are Fortran with directives, once the project is known to be Fortran.
    ambiguous_suffixes={".pf": FORTRAN},
)
