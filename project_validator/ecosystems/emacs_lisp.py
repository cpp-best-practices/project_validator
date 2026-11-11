"""Emacs Lisp: packages built with Eask, Cask or package.el's `<name>-pkg.el`, judged by the Emacs versions CI runs and
by what it runs on the code: ERT or Buttercup tests, undercover.el, package-lint and checkdoc, and byte-compilation
with warnings as errors."""

import re
from collections.abc import Iterator
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import program, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import SettingsReader, matched_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, when
from project_validator.text import pattern

ELISP = frozenset({"Emacs Lisp"})


def _is_tool_directory(directory: Path) -> bool:
    """Eask and Cask install the dependencies in `.eask/` and `.cask/`."""
    return directory.name in (".eask", ".cask")


EASK = BuildSystem(name="Eask", files=("Eask",), languages=ELISP, is_build_tree=_is_tool_directory)
CASK = BuildSystem(name="Cask", files=("Cask",), languages=ELISP, is_build_tree=_is_tool_directory)
PACKAGE_EL = BuildSystem(name="package.el", files=("*-pkg.el",), languages=ELISP)
BUILD_SYSTEMS = frozenset({EASK.name, CASK.name, PACKAGE_EL.name})


def _text(command: Command) -> str:
    return " ".join(resolved(command))


# --- Tests and coverage ---------------------------------------------------------------------------------------------

ELISP_TEST_FILES = TestFiles(
    name="ERT (ert-deftest) or Buttercup tests in test/*.el",
    languages=ELISP,
    path=re.compile(r"(?:^|/)tests?/.+\.el$|-tests?\.el$"),
    contains=re.compile(r"\(ert-deftest\s|\(describe\s+\"|\(buttercup-define-matcher\s"),
)
_ERT_BATCH = re.compile(r"\bert-run-tests-batch(?:-and-exit)?\b")


def _runs_tests(command: Command) -> bool:
    """`eask test ert|buttercup|ert-runner`, `cask exec ert-runner|buttercup`, the runners themselves, or Emacs in
    batch mode running ERT."""
    argv = resolved(command)
    runners = (("eask", "test"), ("cask", "exec", "ert-runner"), ("cask", "exec", "buttercup"), ("ert-runner",))
    if starts_with(argv, *runners, ("buttercup",), ("makem.sh", "test")) is not None:
        return True
    return program(argv) == "emacs" and _ERT_BATCH.search(_text(command)) is not None


ERT = test_runner(
    name="ERT",
    languages=ELISP,
    how="eask test ert test/*.el (or cask exec ert-runner, emacs -batch -l test/x.el -f ert-run-tests-batch-and-exit)",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(ELISP_TEST_FILES.name),
)

UNDERCOVER = "undercover"
_UNDERCOVER = re.compile(r"\(undercover\b|\bundercover\.el\b|\bUNDERCOVER_FORCE\b")


def _read_undercover(path: str, text: str) -> Iterator[Setting]:
    return matched_settings(UNDERCOVER, path, text, {"configured": (_UNDERCOVER, True)})


UNDERCOVER_SETTINGS = SettingsReader(name=UNDERCOVER, files=("*.el",), read=_read_undercover)


def _undercover(command: Command, facts: Facts) -> Run | None:
    """undercover.el counts the lines the tests run: set up in the test files (`(undercover "*.el")`), or on the
    command line, when the tests run."""
    if not _runs_tests(command):
        return None
    if _UNDERCOVER.search(_text(command)) or "UNDERCOVER_FORCE" in command.env:
        return measured(Granularity.LINE)
    configured = facts.where(Setting, tool=UNDERCOVER)
    return measured(Granularity.LINE, read=configured) if configured else None


UNDERCOVER_TOOL = coverage_tool(
    name="undercover.el",
    languages=ELISP,
    can={Granularity.LINE: '(undercover "*.el") in the test files, run by eask test ert'},
    measures=_undercover,
    reads=(UNDERCOVER,),
)


# --- Lints and warnings ---------------------------------------------------------------------------------------------

# package-lint checks the package headers and conventions, checkdoc the docstrings; melpazoid runs both (and more).
PACKAGE_LINT = pattern("package-lint", r"\beask\s+lint\s+package\b|(?<![\w-])package-lint\b|\bmelpazoid\b")
CHECKDOC = pattern("checkdoc", r"\beask\s+lint\s+checkdoc\b|(?<![\w-])checkdoc(?:-batch)?\b|\bmelpazoid\b")
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=ELISP,
    requirements=always(required(PACKAGE_LINT, in_files=False), required(CHECKDOC, in_files=False)),
    words=Wording(
        kind="Emacs Lisp lints",
        hint="run eask lint package and eask lint checkdoc (or melpazoid) in CI",
    ),
)

# The byte compiler warns; `byte-compile-error-on-warn` makes a warning fail the compilation, as does Eask's
# `compile --strict`.
ERROR_ON_WARN = pattern("byte-compile-error-on-warn", r"\bbyte-compile-error-on-warn\b")
EASK_STRICT = pattern("eask compile --strict", r"\beask\s+compile\b[^\n]*\s--strict\b")
ELISP_BUILD_SETTINGS = requirement_reader(
    "Emacs Lisp build settings",
    ("Eask", "Cask", "Makefile", "makefile", "GNUmakefile", "*.el"),
    (required(ERROR_ON_WARN),),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=ELISP,
    requirements=always(required(ERROR_ON_WARN), required(EASK_STRICT, in_files=False)),
    any_one=True,
    reads=(ELISP_BUILD_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration, the Eask or Cask file, the Makefile and the sources",
        hint="byte-compile with eask compile --strict, or (setq byte-compile-error-on-warn t) before "
        "batch-byte-compile",
    ),
)

PACKAGE_LINT_ANALYZER = analyzer(
    name="package-lint",
    languages=ELISP,
    how="eask lint package",
    analyses=when(lambda command: PACKAGE_LINT.regex.search(_text(command)) is not None, analysed),
)
CHECKDOC_ANALYZER = analyzer(
    name="checkdoc",
    languages=ELISP,
    how="eask lint checkdoc",
    analyses=when(lambda command: CHECKDOC.regex.search(_text(command)) is not None, analysed),
)


# --- Outputs --------------------------------------------------------------------------------------------------------


def _output(
    name: str, hint: str, artifacts: tuple[str, ...], *, globs: str, paths: tuple[str, ...], tied: frozenset[str]
) -> BuildOutput:
    return BuildOutput(
        name=name,
        hint=hint,
        artifacts=artifacts,
        paths=paths,
        globs=ignored_at_top_level(globs),
        languages=ELISP,
        build_systems=tied,
    )


def _of_packages_and_sources(
    name: str, hint: str, artifacts: tuple[str, ...], *, globs: str, paths: tuple[str, ...]
) -> tuple[BuildOutput, BuildOutput]:
    """An output of packages (whose tools' outputs would hide language-wide ones) and of plain sources alike."""
    packages, sources = (
        _output(name, hint, artifacts, globs=globs, paths=paths, tied=tied) for tied in (BUILD_SYSTEMS, frozenset())
    )
    return packages, sources


BYTE_CODE, BYTE_CODE_OF_SOURCES = _of_packages_and_sources(
    "the byte-compiled files (*.elc)", "consider ignoring *.elc", ("*.elc",), globs=r"\*\.elc", paths=("shop.elc",)
)
AUTOLOADS, AUTOLOADS_OF_SOURCES = _of_packages_and_sources(
    "the generated autoloads (*-autoloads.el)",
    "consider ignoring *-autoloads.el",
    ("*-autoloads.el",),
    globs=r"\*-autoloads\.el|\*-autoloads\.el\*|\*-autoloads\.elc?",
    paths=("shop-autoloads.el",),
)
EASK_DIRECTORY = _output(
    "Eask's directory",
    "consider ignoring .eask/",
    ("/.eask/",),
    globs=r"\.eask",
    paths=directories(".eask"),
    tied=frozenset({EASK.name}),
)
CASK_DIRECTORY = _output(
    "Cask's directory",
    "consider ignoring .cask/",
    ("/.cask/",),
    globs=r"\.cask",
    paths=directories(".cask"),
    tied=frozenset({CASK.name}),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# An Emacs version (`29.4`, `snapshot`): the `version` of purcell/setup-emacs or jcs090218/setup-emacs, counted after
# their own `uses:` line only (every action has a `version` input); a matrix key `emacs-version` or `emacs`; the
# silex/emacs images.
_EMACS_VERSION = r"(\d+\.\d+(?:\.\d+)?|snapshot|release-snapshot)"

ELISP_ECOSYSTEM = Ecosystem(
    label="Emacs Lisp",
    languages=ELISP,
    build_systems=(EASK, CASK, PACKAGE_EL),
    source_suffixes={".el": "Emacs Lisp"},
    # A byte-compiled file is a file of the ecosystem with no language of its own.
    ambiguous_suffixes={".elc": None},
    toolchain=toolchain_patterns(
        "Emacs",
        version=_EMACS_VERSION,
        inputs=("emacs-version",),
        images=("silex/emacs",),
        more=(
            rf"\buses: [\w-]+/setup-emacs@[^\n]*\n(?:(?!uses:)[^\n]*\n)*?version:\s*[\"']?{_EMACS_VERSION}\b",
            rf"\"emacs(?:-version)?\":\s*\"{_EMACS_VERSION}\"",
        ),
        commands=r"\bemacs\b|\beask\b|\bcask\b|\bmakem\.sh\b|\bert-runner\b|\bbuttercup\b|\bmelpazoid\b",
        setup=("emacs",),
    ),
)

EMACS_VERSIONS = versions_axis("Emacs version", "Emacs", ELISP)
