"""Nix: flakes (`flake.nix`) and plain expressions (`default.nix`, `shell.nix`), judged by what CI builds and checks
(`nix flake check`, `nix build` of the checks), by the formatter it runs (nixfmt, alejandra, nixpkgs-fmt, or the
flake's own through `nix fmt`), by the lints statix and deadnix (the warnings Nix does not have, errors with
`deadnix --fail`), by the systems it builds for (the platform axis: `x86_64-linux`, `aarch64-darwin`, …, or the
runner's own) and by the `result` symlinks `nix build` leaves, which must be ignored. What nix runs in turn (`nix run
nixpkgs#statix -- check .`, `nix develop -c pytest`) is followed, so the tools claim it. `flake.lock` as a dependency
rule waits for its check (#24)."""

from __future__ import annotations

import re

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import starts_with
from project_validator.facts.axes import ToolchainAxis, toolchain_versions
from project_validator.facts.expansion import CommandExpander, Expansion, Launched
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.jobs import Job
from project_validator.facts.outputs import BuildOutput, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Requirement, Wording, always
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, defined_by, starts, when

NIX_LANGUAGE = "Nix"
NIX = frozenset({NIX_LANGUAGE})

FLAKE = BuildSystem(name="Nix flake", files=("flake.nix",), languages=NIX)
EXPRESSIONS = BuildSystem(name="Nix", files=("default.nix", "shell.nix"), languages=NIX)
BUILD_SYSTEMS = frozenset({FLAKE.name, EXPRESSIONS.name})


# --- Tests: the flake's checks ---------------------------------------------------------------------------------------

FLAKE_CHECKS = TestFiles(
    name="flake checks (a checks output in flake.nix)",
    languages=NIX,
    path=re.compile(r"(?:^|/)flake\.nix$"),
    contains=re.compile(r"\bchecks\b"),
)


def _runs_checks(command: Command, _facts: Facts) -> Run | None:
    """`nix flake check` builds every check; `nix build` does when it names them (`.#checks.x86_64-linux.tests`)."""
    argv = resolved(command)
    if starts_with(argv, ("nix", "flake", "check")) is not None:
        return tested()
    return tested() if starts_with(argv, ("nix", "build")) and any("checks" in word for word in argv) else None


FLAKE_CHECK = test_runner(
    name="nix flake check",
    languages=NIX,
    how="nix flake check (or nix build .#checks.<system>.<check>)",
    runs=_runs_checks,
    tests=tests_of(FLAKE_CHECKS.name),
)


# --- Formatting -----------------------------------------------------------------------------------------------------

# nixfmt and alejandra each have one style; `nix fmt` runs the flake's `formatter` output, whatever its style.
NIXFMT = format_tool(
    name="nixfmt",
    languages=NIX,
    can={Enforcement.CHECK: "nixfmt --check .", Enforcement.APPLY: "nixfmt ."},
    formats=flagged(("nixfmt",), ("nixpkgs-fmt",), checks=("--check", "-c")),
    style=defined_by(),
)
ALEJANDRA = format_tool(
    name="alejandra",
    languages=NIX,
    can={Enforcement.CHECK: "alejandra --check .", Enforcement.APPLY: "alejandra ."},
    formats=flagged(("alejandra",), checks=("--check", "-c")),
    style=defined_by(),
)


def _nix_fmt(command: Command, facts: Facts) -> Run | None:
    """`nix fmt` applies the flake's formatter; with `--check` (or `-c`) passed through, it checks (the formatter
    must take it: nixfmt, alejandra and treefmt do)."""
    return flagged(("nix", "fmt"), checks=("--check", "-c", "--fail-on-change"))(command, facts)


NIX_FMT = format_tool(
    name="nix fmt",
    languages=NIX,
    can={Enforcement.CHECK: "nix fmt -- --check .", Enforcement.APPLY: "nix fmt"},
    formats=_nix_fmt,
    style=defined_by(),
)


# --- Lints: the warnings Nix does not have --------------------------------------------------------------------------

STATIX = analyzer(
    name="statix",
    languages=NIX,
    how="statix check .",
    analyses=when(starts(("statix", "check")), analysed),
)
DEADNIX = analyzer(
    name="deadnix",
    languages=NIX,
    how="deadnix --fail .",
    analyses=when(starts(("deadnix",)), analysed),
)
STATIX_RUNS = Requirement(name="statix", tools=("statix",))
DEADNIX_RUNS = Requirement(name="deadnix", tools=("deadnix",))
# statix check exits non-zero on a finding; deadnix only with --fail (-f).
STATIX_FAILS = Requirement(name="statix check, which fails on any finding", tools=("statix",))
DEADNIX_FAILS = Requirement(
    name="deadnix --fail", runs=re.compile(r"\bdeadnix\b(?=.*\s(?:--fail|-f)\b)"), hints=("deadnix",)
)

WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=NIX,
    requirements=always(STATIX_RUNS, DEADNIX_RUNS),
    words=Wording(
        kind="Nix lints",
        searched="CI configuration",
        hint="run statix check and deadnix over the expressions in CI (nix run nixpkgs#statix -- check .)",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=NIX,
    requirements=always(STATIX_FAILS, DEADNIX_FAILS),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration",
        hint="run statix check (which fails on any finding) and deadnix --fail in CI",
    ),
)


# --- Outputs --------------------------------------------------------------------------------------------------------

RESULT_LINKS = BuildOutput(
    languages=NIX,
    build_systems=BUILD_SYSTEMS,
    name="the result symlinks nix build leaves",
    globs=ignored_at_top_level(r"result|result-\*|result\*"),
    paths=("result", "result-bin"),
    hint="consider ignoring result and result-*",
    artifacts=("result", "result-*"),
)


# --- Launchers: the commands nix runs in turn -------------------------------------------------------------------------


def _installable_program(installable: str) -> str:
    """The program an installable names: `nixpkgs#statix` and `.#checks.x86_64-linux.statix` run statix."""
    return installable.rpartition("#")[2].rpartition(".")[2] or installable


def _nix_launched(command: Command, _context: Context) -> list[Expansion] | None:
    """`nix run <installable> -- <arguments>` runs the installable's program with the arguments; `nix develop [<flake>]
    -c <command>` and `nix shell <installables> -c <command>` run the command after `-c` (or `--command`)."""
    argv = resolved(command)
    if starts_with(argv, ("nix", "run")) is not None:
        words = argv[2:]
        installable = next((word for word in words if not word.startswith("-")), None)
        if installable is None or "--" not in words:
            return []
        return [Launched(argv=(_installable_program(installable), *words[words.index("--") + 1 :]))]
    if starts_with(argv, ("nix", "develop"), ("nix", "shell")) is None:
        return None
    flag = next((word for word in argv if word in ("-c", "--command")), None)
    launched = argv[argv.index(flag) + 1 :] if flag is not None else ()
    return [Launched(argv=launched)] if launched else []


NIX_LAUNCHERS = CommandExpander(name="nix run", expand=_nix_launched)


# --- Recognition, toolchain and the systems axis ---------------------------------------------------------------------

# The version a job that uses a toolchain without naming one gets (`project_validator.platforms.DEFAULT_VERSION`).
DEFAULT_VERSION = "default"
_SYSTEMS = r"(?:x86_64|aarch64|i686|armv7l|riscv64|powerpc64le)-(?:linux|darwin)"
# The system a runner builds for, when the job names none.
_RUNNER_SYSTEMS = {"linux": "x86_64-linux", "macos": "aarch64-darwin"}

NIX_ECOSYSTEM = Ecosystem(
    label="Nix",
    languages=NIX,
    build_systems=(FLAKE, EXPRESSIONS),
    source_suffixes={".nix": NIX_LANGUAGE},
    # Nix names no version a job builds with; the systems it builds for are what varies (`system: aarch64-linux`).
    toolchain=toolchain_patterns(
        NIX_LANGUAGE,
        programs=(
            "nix",
            "nix-build",
            "nix-shell",
            "nix-env",
            "nix-instantiate",
            "nixfmt",
            "nixpkgs-fmt",
            "alejandra",
            "statix",
            "deadnix",
            "cachix",
        ),
        actions=("install-nix-action", "nix-installer-action", "nix-quick-install-action", "cachix-action"),
        labelled=((re.compile(rf"\b({_SYSTEMS})\b"), "{}"),),
    ),
)


def _systems(job: Job) -> frozenset[str]:
    """The systems a job builds for: those it names, else its runner's own when it uses Nix (none on Windows)."""
    named = toolchain_versions(job.toolchains, NIX_LANGUAGE)
    if named - {DEFAULT_VERSION}:
        return frozenset(named - {DEFAULT_VERSION})
    runner = _RUNNER_SYSTEMS.get(job.os)
    return frozenset({runner}) if named and runner is not None else frozenset()


def _runner_system(job: Job) -> bool:
    return toolchain_versions(job.toolchains, NIX_LANGUAGE) == {DEFAULT_VERSION}


SYSTEMS = ToolchainAxis(languages=NIX, noun="system", of_job=_systems, runner_default=_runner_system)


__all__ = ["NIX_ECOSYSTEM", "SYSTEMS"]
