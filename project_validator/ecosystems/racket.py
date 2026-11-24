"""Racket: packages described by `info.rkt`, judged by the Racket versions and variants (CS, BC) CI runs and by the raco
commands it runs: `raco test`, `raco cover` and `raco fmt`."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.coverage import Granularity, coverage_tool, reported
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.jobs import Job
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import defined_by, starts, when

RACKET = frozenset({"Racket"})


def _is_compiled_directory(directory: Path) -> bool:
    """Racket writes the compiled `.zo` files in a `compiled` directory beside each module."""
    return directory.name == "compiled"


RACO_PKG = BuildSystem(name="raco pkg", files=("info.rkt",), languages=RACKET, is_build_tree=_is_compiled_directory)


# `(define license 'MIT)`, or a list for a compound expression: `(define license '(Apache-2.0 OR MIT))`.
_LICENSE = re.compile(r"\(define\s+license\s+'(?:\((?P<list>[^()]*(?:\([^()]*\)[^()]*)*)\)|(?P<one>[^\s()]+))")


def _info_license(text: str) -> str | None:
    """The SPDX expression a package's info.rkt declares as its `license`."""
    if (match := _LICENSE.search(text)) is None:
        return None
    return match["one"] or " ".join(match["list"].split()) or None


INFO_LICENSE = declared_license_reader(
    name="info.rkt license", files=("info.rkt",), languages=RACKET, declared=_info_license
)

# --- Tests and coverage ---------------------------------------------------------------------------------------------

# rackunit tests: in a `test` submodule, or a module that requires rackunit.
RACKET_TEST_FILES = TestFiles(
    name="rackunit tests (module+ test) in .rkt files",
    languages=RACKET,
    path=re.compile(r"\.rkt$"),
    contains=re.compile(r"\(module\+\s+test\b|\(require\s+(?:[^()]*\s)?rackunit\b|\(test-case\b|\(check-\w+\b"),
)


def _package_ci(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """jackfirth/racket-package-ci-action installs the package (`name`, in `directory`) linked and runs its tests."""
    name, directory = inputs.get("name", ""), inputs.get("directory", ".")
    source = () if directory == "." else (directory,)
    return (
        ("raco", "pkg", "install", "--name", name, "--batch", "--auto", "--link", *source),
        ("raco", "test", "--package", "--drdr", name),
    )


RACKET_PACKAGE_CI_ACTION = Action(name="jackfirth/racket-package-ci-action", runs=_package_ci)

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
    measures=when(starts(("raco", "cover")), lambda: reported(Granularity.STATEMENT)),
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

# A package of tests, as Racket's multi-package convention writes it: in the `tests` collection (koyo-test), or
# described as tests for another package (typed-racket-test, scribble-test).
_TEST_PACKAGE = re.compile(r'\(define\s+collection\s+"tests"\s*\)|\(define\s+pkg-desc\s+"tests\s+for\b')


def _test_packages(project: Project) -> frozenset[str]:
    """The directories of the project's Racket packages of tests."""
    return frozenset(
        str(PurePosixPath(path).parent)
        for path in project.files()
        if PurePosixPath(path).name == "info.rkt" and _TEST_PACKAGE.search(project.read_text(path))
    )


RACKET_ECOSYSTEM = Ecosystem(
    label="Racket",
    languages=RACKET,
    build_systems=(RACO_PKG,),
    test_units=_test_packages,
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


def _default_variant(version: str) -> str:
    """The variant setup-racket installs for `version` when told none: CS from Racket 8.0 on (and for `stable`,
    `current` and `pre-release`), BC before."""
    major = version.partition(".")[0]
    return "BC" if major.isdigit() and int(major) < 8 else "CS"


def _racket_platforms(job: Job) -> frozenset[str]:
    """A job's toolchains: each Racket version it names with the variant it names (`8.14 BC`), or the version alone;
    a version's default variant is not named (`8.14 CS` is `8.14`), so a job that names it and one that does not run
    one version."""
    found = toolchain_versions(job.toolchains, "Racket")
    variants = {name.removeprefix("variant ") for name in found if name.startswith("variant ")}
    versions = found - {f"variant {variant}" for variant in variants}
    if versions and variants:
        return frozenset(
            version if variant == _default_variant(version) else f"{version} {variant}"
            for version in versions
            for variant in variants
        )
    return versions or frozenset(variants)


RACKET_VERSIONS = ToolchainAxis(languages=RACKET, noun="Racket version", of_job=_racket_platforms)
