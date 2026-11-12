"""Racket: packages described by `info.rkt`, judged by the Racket versions and variants (CS, BC) CI runs and by the raco
commands it runs: `raco test`, `raco cover` and `raco fmt`."""

from __future__ import annotations

import re
from pathlib import Path

from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

RACKET = frozenset({"Racket"})


def _is_compiled_directory(directory: Path) -> bool:
    """Racket writes the compiled `.zo` files in a `compiled` directory beside each module."""
    return directory.name == "compiled"


RACO_PKG = BuildSystem(name="raco pkg", files=("info.rkt",), languages=RACKET, is_build_tree=_is_compiled_directory)


# --- Tests and coverage ---------------------------------------------------------------------------------------------

# rackunit tests: in a `test` submodule, or a module that requires rackunit.
RACKET_TEST_FILES = TestFiles(
    name="rackunit tests (module+ test) in .rkt files",
    languages=RACKET,
    path=re.compile(r"\.rkt$"),
    contains=re.compile(r"\(module\+\s+test\b|\(require\s+(?:[^()]*\s)?rackunit\b|\(test-case\b|\(check-\w+\b"),
)

# `raco cover` runs the tests too, instrumented.
_RUNS_TESTS = starts(("raco", "test"), ("raco", "cover"))

RACO_TEST = test_runner(
    name="raco test",
    languages=RACKET,
    how="raco test .",
    runs=when(_RUNS_TESTS, tested),
    tests=tests_of(RACKET_TEST_FILES.name),
)
# cover measures expression coverage, the finest Racket has.
RACO_COVER = coverage_tool(
    name="raco cover",
    languages=RACKET,
    can={Granularity.STATEMENT: "raco cover . (expression coverage; -f codecov or coveralls to upload)"},
    measures=when(starts(("raco", "cover")), lambda: measured(Granularity.STATEMENT)),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# `raco fmt -i` rewrites the files (and enforces the style where the job fails on the diff); without `-i` it only
# prints the formatted code. The formatter has one style, with `.fmt.rkt` for options.
RACO_FMT = format_tool(
    name="raco fmt",
    languages=RACKET,
    can={Enforcement.APPLY: "raco fmt -i $(git ls-files '*.rkt'), with the job failing on git diff --exit-code"},
    formats=flagged(("raco", "fmt"), checks=(), applies=("-i", "--in-place")),
    style=defined_by(),
)


# --- Outputs --------------------------------------------------------------------------------------------------------

COMPILED_DIRECTORIES = BuildOutput(
    languages=RACKET,
    name="the compiled directories",
    globs=ignored_at_top_level(r"compiled"),
    paths=(*directories("compiled"), "src/compiled/", "src/compiled/main_rkt.zo"),
    hint="consider ignoring compiled/ (raco make and raco test write one beside each module)",
    artifacts=("compiled/",),
)


# --- Recognition and toolchains -------------------------------------------------------------------------------------

# Bogdanp/setup-racket's `version` (`8.14`, `stable`, `current`) and `variant` (`CS`, `BC`): a `version` input is
# any action's, so both count after setup-racket's own `uses:` line only; a matrix key `racket-version` or `racket`;
# the racket/racket images (`8.14-full`).
_RACKET_VERSION = r"(\d+(?:\.\d+)*|stable|current|pre-release)"
_SETUP_RACKET = r"\buses: [\w-]+/setup-racket@[^\n]*\n(?:(?!uses:)[^\n]*\n)*?"

# The variant rides along as a labelled toolchain ("variant CS"), paired with the versions by the axis.
_VARIANTS = (
    (re.compile(rf"{_SETUP_RACKET}variant:\s*[\"']?(CS|BC)\b"), "variant {}"),
    (re.compile(r"\"variant\":\s*\"(CS|BC)\""), "variant {}"),
)

RACKET_ECOSYSTEM = Ecosystem(
    label="Racket",
    languages=RACKET,
    build_systems=(RACO_PKG,),
    source_suffixes={".rkt": "Racket"},
    # Scribble documents and `.rktd` data are files of the ecosystem with no language of their own; `.rktl` is Racket.
    ambiguous_suffixes={".rktl": "Racket", ".scrbl": None, ".rktd": None},
    toolchain=toolchain_patterns(
        "Racket",
        version=_RACKET_VERSION,
        inputs=("racket-version",),
        images=("racket/racket",),
        more=(
            rf"{_SETUP_RACKET}version:\s*[\"']?{_RACKET_VERSION}\b",
            rf"\"racket(?:-version)?\":\s*\"{_RACKET_VERSION}\"",
        ),
        programs=(
            *subcommands("raco", "test", "pkg", "setup", "make", "cover", "fmt", "exe", "dist", "check-requires"),
            "racket",
        ),
        setup=("racket",),
        labelled=_VARIANTS,
    ),
)


def _racket_platforms(job: Job) -> frozenset[str]:
    """A job's toolchains: each Racket version it names with the variant it names (`8.14 CS`), or the version alone."""
    found = toolchain_versions(job.toolchains, "Racket")
    variants = {name.removeprefix("variant ") for name in found if name.startswith("variant ")}
    versions = found - {f"variant {variant}" for variant in variants}
    if versions and variants:
        return frozenset(f"{version} {variant}" for version in versions for variant in variants)
    return versions or frozenset(variants)


RACKET_VERSIONS = ToolchainAxis(languages=RACKET, noun="Racket version", of_job=_racket_platforms)
