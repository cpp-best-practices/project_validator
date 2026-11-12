"""R: packages described by a `DESCRIPTION` file, judged by the R versions CI runs and by the R code CI runs on the
package: `R CMD check` and rcmdcheck, testthat, covr, lintr, styler and air.

CI runs R code in three ways, which `r_code` reads alike: `Rscript -e "covr::codecov()"` (or `R -e`), a step whose
`shell: Rscript {0}` runs its script (the GitHub Actions layer makes it one `Rscript` command given the script), and the
r-lib/actions, whose `check-r-package` runs rcmdcheck with its inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, program, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required
from project_validator.facts.settings import file_reader
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, when
from project_validator.text import pattern
from project_validator.tools.limits import function_length_limiters

R = frozenset({"R"})
DESCRIPTION = "DESCRIPTION"
_PACKAGE_FIELD = re.compile(r"^Package:\s*\S", re.MULTILINE)


def _package_languages(_path: str, text: str) -> frozenset[str]:
    """A `DESCRIPTION` with a `Package:` field describes an R package; another file so named is not one."""
    return R if _PACKAGE_FIELD.search(text) else frozenset()


def _is_check_directory(directory: Path) -> bool:
    """`R CMD check` writes `<package>.Rcheck` beside the package."""
    return directory.name.endswith(".Rcheck")


R_PACKAGE = BuildSystem(
    name="R package", files=(DESCRIPTION,), declared_languages=_package_languages, is_build_tree=_is_check_directory
)


def r_code(command: Command) -> str:
    """The R code a command runs: the expressions `Rscript -e` or `R -e` is given, or the script `Rscript` runs
    (its text, for a step with `shell: Rscript {0}`); "" for another command."""
    argv = resolved(command)
    name = program(argv)
    if name not in ("Rscript", "R"):
        return ""
    expressions = option_values(argv, "-e")
    if expressions or name == "R":
        return "\n".join(expressions)
    return "\n".join(word for word in argv[1:] if not word.startswith("-"))


def _calls(regex: str) -> re.Pattern[str]:
    return re.compile(rf"\b(?:{regex})\s*\(")


# --- Tests and coverage ---------------------------------------------------------------------------------------------

# testthat's tests, and tinytest's.
R_TEST_FILES = TestFiles(
    name="testthat (tests/testthat/test-*.R) or tinytest (inst/tinytest/test_*.R) files",
    languages=R,
    path=re.compile(r"(?:^|/)(?:tests/testthat/test[-_][^/]+|inst/tinytest/test_[^/]+)\.[Rr]$"),
    contains=re.compile(r"\b(?:test_that|describe|it|expect_\w+)\s*\("),
)

# What runs the tests: `R CMD check` (which runs them), rcmdcheck, devtools, testthat and tinytest called from R.
_TEST_CALLS = _calls(
    r"rcmdcheck::rcmdcheck|devtools::(?:test|check)|testthat::test_(?:dir|local|package|check|file)"
    r"|tinytest::(?:test_package|run_test_dir)|test_check"
)


def _runs_tests(command: Command) -> bool:
    argv = resolved(command)
    return starts_with(argv, ("R", "CMD", "check")) is not None or _TEST_CALLS.search(r_code(command)) is not None


R_TESTS = test_runner(
    name="R CMD check",
    languages=R,
    how="R CMD check (or rcmdcheck::rcmdcheck(), r-lib/actions/check-r-package, devtools::test())",
    runs=lambda command, _facts: tested() if _runs_tests(command) else None,
    tests=tests_of(R_TEST_FILES.name),
)


def _rcmdcheck(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """What r-lib/actions/check-r-package runs: rcmdcheck with the action's inputs (its `error-on` is `"warning"` by
    default)."""
    args = inputs.get("args", 'c("--no-manual", "--as-cran")')
    error_on = inputs.get("error-on", '"warning"')
    return (("Rscript", "-e", f"rcmdcheck::rcmdcheck(args = ({args}), error_on = ({error_on}))"),)


CHECK_R_PACKAGE = Action(name="r-lib/actions/check-r-package", runs=_rcmdcheck)

# covr counts lines, the finest R has: a package's coverage, or the report uploads.
_COVR = _calls(r"covr::(?:package_coverage|codecov|coveralls|report|to_cobertura|file_coverage|azure|gitlab)")

COVR = coverage_tool(
    name="covr",
    languages=R,
    can={Granularity.LINE: "covr::package_coverage() (or covr::codecov())"},
    measures=lambda command, _facts: reported(Granularity.LINE) if _COVR.search(r_code(command)) else None,
)


# --- Formatting -----------------------------------------------------------------------------------------------------

_STYLER = _calls(r"styler::style_(?:pkg|dir|file)")


def _styler(command: Command, facts: Facts) -> Run | None:
    """styler rewrites the files (from R, or as the `style-files` pre-commit hook): it enforces the style where the
    job fails on the diff or commits it."""
    argv = resolved(command)
    if _STYLER.search(r_code(command)) or starts_with(argv, ("style-files",)) is not None:
        return formatted(command, facts, checks=False)
    return None


STYLER = format_tool(
    name="styler",
    languages=R,
    can={Enforcement.APPLY: "styler::style_pkg(), with the job failing on git diff --exit-code"},
    formats=_styler,
    style=defined_by(),
)
# air has a default style; `air.toml` is optional.
AIR = format_tool(
    name="air",
    languages=R,
    can={Enforcement.CHECK: "air format --check .", Enforcement.APPLY: "air format ."},
    formats=flagged(("air", "format"), checks=("--check",)),
    style=defined_by(),
)


# --- Warnings and analysis ------------------------------------------------------------------------------------------

# R has no compiler warnings; lintr's lints stand in. `lintr::lint_package()` only prints them unless
# `LINTR_ERROR_ON_LINT` (or `error_on_lint`) is set; the pre-commit hook fails on them by itself.
LINTR = pattern("lintr", r"\blintr::lint(?:_package|_dir)?\s*\(|\Alintr(?:\s|\Z)")
LINTR_FAILS = pattern(
    "failing on lints (LINTR_ERROR_ON_LINT)",
    r"\bLINTR_ERROR_ON_LINT=(?i:true|1|yes)\b|\berror_on_lint\s*=\s*TRUE\b|\Alintr(?:\s|\Z)",
)

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=R,
    requirements=always(required(LINTR, in_files=False), required(LINTR_FAILS, in_files=False)),
    words=Wording(
        kind="R lints",
        hint="run lintr::lint_package() in CI with LINTR_ERROR_ON_LINT=true (or the lintr pre-commit hook)",
    ),
)

# rcmdcheck (and r-lib/actions/check-r-package, by default) fails the check on a WARNING or a NOTE.
ERROR_ON_WARNING = pattern('rcmdcheck error_on = "warning"', r"""\berror_on\s*=\s*\(?\s*["'](?:warning|note)["']""")
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=R,
    requirements=always(required(ERROR_ON_WARNING, in_files=False)),
    any_one=True,
    words=Wording(
        kind="warnings as errors",
        hint='check the package with rcmdcheck::rcmdcheck(error_on = "warning") (r-lib/actions/check-r-package does '
        "by default) rather than R CMD check alone, which fails only on an ERROR",
    ),
)

LINTR_SETTINGS = file_reader("lintr", (".lintr",))
LINTR_ANALYZER = analyzer(
    name="lintr",
    languages=R,
    how="lintr::lint_package()",
    analyses=when(lambda command: LINTR.regex.search(" ".join(resolved(command))) is not None, analysed),
    rules=defined_by(files=(LINTR_SETTINGS.name,)),
)

FUNCTION_LENGTH_LIMITERS = function_length_limiters(R)


# --- Outputs --------------------------------------------------------------------------------------------------------


def _session_file(name: str) -> BuildOutput:
    return BuildOutput(
        languages=R,
        name=f"the {name} session file",
        globs=ignored_at_top_level(re.escape(name)),
        paths=(name,),
        hint=f"consider ignoring {name}",
        artifacts=(name,),
    )


R_HISTORY = _session_file(".Rhistory")
R_DATA = _session_file(".RData")
RSTUDIO_STATE = BuildOutput(
    languages=R,
    name="RStudio's project state",
    globs=ignored_at_top_level(r"\.Rproj\.user"),
    paths=directories(".Rproj.user"),
    hint="consider ignoring .Rproj.user/",
    artifacts=(".Rproj.user/",),
)
CHECK_DIRECTORY = BuildOutput(
    languages=R,
    name="R CMD check's directory",
    globs=ignored_at_top_level(r"\*\.Rcheck|[\w.-]+\.Rcheck"),
    paths=directories("shop.Rcheck"),
    hint="consider ignoring *.Rcheck/",
    artifacts=("*.Rcheck/",),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# r-lib/actions/setup-r's `r-version`: a version, or `release`, `devel`, `next`, `oldrel-1`; the rocker images.
_R_VERSION = r"(\d+\.\d+(?:\.\d+)?|release|devel|next|oldrel(?:-\d+)?)"

R_ECOSYSTEM = Ecosystem(
    label="R",
    languages=R,
    build_systems=(R_PACKAGE,),
    source_suffixes={".R": "R"},
    # `.r` is REBOL's too; R Markdown, Quarto, Sweave, Rd documentation and RStudio project files are files of the
    # ecosystem with no language of their own.
    ambiguous_suffixes={".r": "R", ".Rmd": None, ".qmd": None, ".Rnw": None, ".Rd": None, ".Rproj": None},
    toolchain=toolchain_patterns(
        "R",
        version=_R_VERSION,
        inputs=("r-version",),
        images=("rocker/r-ver", "rocker/tidyverse", "rocker/verse", "rocker/rstudio", "r-base"),
        programs=("Rscript", ("R", "CMD"), ("R", "-e"), ("R", "-q"), ("R", "--vanilla")),
        actions=("r-lib/actions",),
        setup=("r",),
    ),
)

R_VERSIONS = versions_axis("R version", "R", R)
