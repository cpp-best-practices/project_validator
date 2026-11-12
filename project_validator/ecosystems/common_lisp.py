"""Common Lisp: systems defined with ASDF (`*.asd`), judged by the Lisp implementations CI runs (SBCL, CCL, ECL, ABCL,
through Roswell or 40ants/setup-lisp) and by what it runs on the code: the system's `test-op`, sb-cover, sblint, and
the compiler's warnings made errors. Lisp code CI runs on a command line (`sbcl --eval "(asdf:test-system :shop)"`)
is read as the words of the command."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.expansion import Action, launcher
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import SettingsReader, matched_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, starts, when
from project_validator.text import pattern

LISP = frozenset({"Common Lisp"})


def _is_qlot_directory(directory: Path) -> bool:
    """Qlot installs the project's dependencies in `.qlot/`."""
    return directory.name == ".qlot"


ASDF = BuildSystem(name="ASDF", files=("*.asd",), languages=LISP, is_build_tree=_is_qlot_directory)
# `qlot exec sblint shop.asd` runs the command with the project's dependencies.
QLOT_EXEC = launcher("qlot exec", (("qlot", "exec"),))


def _code(command: Command) -> str:
    """The command as one text, Lisp forms included (`--eval "(asdf:test-system :shop)"` is a word of it)."""
    return " ".join(resolved(command))


# --- Tests and coverage ---------------------------------------------------------------------------------------------

# FiveAM, Parachute, Rove and Prove tests, in the test system's files.
LISP_TEST_FILES = TestFiles(
    name="FiveAM, Parachute, Rove or Prove tests (tests/*.lisp)",
    languages=LISP,
    path=re.compile(r"(?:^|/)(?:tests?|t)/.+\.lisp$|-tests?\.lisp$"),
    contains=re.compile(
        r"\((?:(?:fiveam|5am|it\.bese\.fiveam):)?(?:def-suite\*?|def-test|test)\s"
        r"|\((?:parachute:)?define-test\s|\((?:rove:)?deftest\s|\((?:prove:)?(?:subtest|plan)\s"
    ),
)
_RUNS_TESTS = re.compile(
    r"\(asdf:test-system\b|\(asdf:oos\s+'asdf:test-op|\(asdf:operate\s+'asdf:test-op"
    r"|\((?:rove|fiveam|5am|parachute|prove):(?:run!?|run-all-tests|test|run-system-tests)\b"
)


def _runs_tests(command: Command) -> bool:
    """The system's `test-op`, a test framework's runner called from Lisp, or `rove` on the system definition."""
    return program(resolved(command)) == "rove" or _RUNS_TESTS.search(_code(command)) is not None


ASDF_TEST = test_runner(
    name="asdf:test-system",
    languages=LISP,
    how='sbcl --non-interactive --eval "(asdf:test-system :shop)" (or rove shop.asd, 40ants/run-tests)',
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(LISP_TEST_FILES.name),
)


def _run_tests_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """What 40ants/run-tests runs: the `run-tests` code it is given, or the `asdf-system`'s `test-op`; with a
    `coveralls-token`, under sb-cover."""
    system = inputs.get("asdf-system", "")
    code = inputs.get("run-tests") or (f"(asdf:test-system :{system})" if system else "(asdf:test-system)")
    coverage = ("--eval", "(require :sb-cover)") if inputs.get("coveralls-token") else ()
    return (("ros", "run", *coverage, "--eval", code),)


RUN_TESTS_ACTION = Action(name="40ants/run-tests", runs=_run_tests_action)

SB_COVER = "sb-cover"
_SB_COVER = re.compile(r"\bsb-cover\b")


def _read_sb_cover(path: str, text: str) -> Iterator[Setting]:
    return matched_settings(SB_COVER, path, text, {"required": (_SB_COVER, True)})


# A script CI loads (`sbcl --load ci/coverage.lisp`) may be what requires sb-cover.
SB_COVER_SETTINGS = SettingsReader(name=SB_COVER, files=("*.lisp", "*.ros"), read=_read_sb_cover)


def _sb_cover(command: Command, facts: Facts) -> Run | None:
    """sb-cover instruments SBCL's compiled code for expression and branch coverage: required on the command line,
    or by a script, when the tests run."""
    if not _runs_tests(command):
        return None
    if _SB_COVER.search(_code(command)):
        return measured(Granularity.BRANCH)
    scripted = facts.where(Setting, tool=SB_COVER)
    return measured(Granularity.BRANCH, read=scripted) if scripted else None


SB_COVER_TOOL = coverage_tool(
    name="sb-cover",
    languages=LISP,
    can={Granularity.BRANCH: '(require :sb-cover) before the tests, with (sb-cover:report "coverage/") after'},
    measures=_sb_cover,
    reads=(SB_COVER,),
)


# --- Warnings -------------------------------------------------------------------------------------------------------

# SBCL's compiler warns (and notes); sblint runs the compiler over the system and reports them in CI.
# `ros install cxxxr/sblint` installs it: a slash before the name is not a run.
SBLINT = pattern("sblint", r"(?<![\w/-])sblint\b")
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=LISP,
    requirements=always(required(SBLINT, in_files=False)),
    words=Wording(kind="Lisp compiler lints", hint="run sblint over the system definition in CI (sblint shop.asd)"),
)
# UIOP's compile-file behaviour: `:error` fails the build on a compiler warning (`-warnings-`) or on a compile failure
# (`-failure-`, the warnings that signal failure).
COMPILE_ERRORS = pattern(
    "uiop:*compile-file-warnings-behaviour* :error",
    r"\*compile-file-(?:warnings|failure)-behaviour\*[^\n()]*:error\b",
)
LISP_SETTINGS = requirement_reader(
    "Lisp build settings", ("*.asd", "*.lisp", "*.ros", ".sbclrc", ".ccl-init.lisp"), (required(COMPILE_ERRORS),)
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=LISP,
    requirements=always(required(COMPILE_ERRORS)),
    any_one=True,
    reads=(LISP_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration, the system definitions and the Lisp sources",
        hint="(setf uiop:*compile-file-warnings-behaviour* :error) before building in CI, so that a compiler warning "
        "fails the build",
    ),
)

SBLINT_ANALYZER = analyzer(
    name="sblint", languages=LISP, how="sblint shop.asd", analyses=when(starts(("sblint",)), analysed)
)


# --- Outputs --------------------------------------------------------------------------------------------------------

# Compiled files: SBCL's .fasl, CCL's .lx64fsl and .dx64fsl, ECL's .fas, CLISP's .fas.
FASL_FILES = BuildOutput(
    languages=LISP,
    name="the compiled files (*.fasl)",
    globs=ignored_at_top_level(r"\*\.fasl|\*\.fas|\*\.[ld]x64fsl|\*\.\*fsl"),
    paths=("src/shop.fasl", "src/shop.fas", "src/shop.lx64fsl"),
    hint="consider ignoring *.fasl (and *.fas, *.lx64fsl, *.dx64fsl)",
    artifacts=("*.fasl", "*.fas", "*.lx64fsl", "*.dx64fsl", "*.wx64fsl"),
)
QLOT_DIRECTORY = BuildOutput(
    languages=LISP,
    name="Qlot's directory",
    globs=ignored_at_top_level(r"\.qlot"),
    paths=directories(".qlot"),
    hint="consider ignoring .qlot/ (qlot install writes it)",
    artifacts=("/.qlot/",),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# An implementation as Roswell names it (`sbcl-bin`, `ccl-bin/1.12.2`, `ecl`), in `LISP` (40ants/setup-lisp reads the
# variable), `ros install` or `ros use`, or a matrix key `lisp`; the clfoundation images name one too.
_IMPLEMENTATION = r"((?:sbcl|ccl|ecl|abcl|clasp|clisp|cmucl|allegro|lispworks)(?:-bin)?(?:/[\w.-]+)?)"

LISP_ECOSYSTEM = Ecosystem(
    label="Common Lisp",
    languages=LISP,
    build_systems=(ASDF,),
    source_suffixes={".lisp": "Common Lisp"},
    # `.cl` is OpenCL's too; Roswell scripts and `.lsp` files are Lisp once the project is; a system definition and a
    # qlfile are files of the ecosystem with no language of their own.
    ambiguous_suffixes={".cl": "Common Lisp", ".ros": "Common Lisp", ".lsp": "Common Lisp", ".asd": None},
    toolchain=toolchain_patterns(
        "Lisp",
        version=_IMPLEMENTATION,
        inputs=("LISP", "lisp", "lisp-implementation"),
        more=(
            rf"\bros\s+(?:install|use)\s+{_IMPLEMENTATION}\b",
            r"\bclfoundation/((?:sbcl|ccl|ecl|abcl)(?::[\w.-]+)?)",
        ),
        programs=("ros", "sbcl", "ccl", "ccl64", "ecl", "abcl", "qlot", "rove", "sblint"),
        actions=("40ants/",),
        setup=("lisp",),
    ),
)

LISP_IMPLEMENTATIONS = versions_axis("Lisp implementation", "Lisp", LISP)
