"""The Nix profile's rules, judged by the generic checks in the flake and plain expressions layouts."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.nix import NIX_ECOSYSTEM
from tests.support import GITHUB_WORKFLOW, github_job, make_context, run_as, run_in_layout, temp_project, uses

NIX = frozenset({"Nix"})
NIX_MATRIX = """\
    jobs:
      build:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            include:
              - { os: ubuntu-latest, system: x86_64-linux }
              - { os: ubuntu-latest, system: aarch64-linux }
              - { os: macos-latest, system: aarch64-darwin }
        steps:
          - uses: DeterminateSystems/nix-installer-action@v23
          - run: nix build .#packages.${{ matrix.system }}.default
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_flakes_expressions_and_nix_sources(self) -> None:
        with temp_project({"flake.nix": "{ }\n", "lib/shop.nix": "{ }\n"}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (NIX, frozenset({"Nix flake"})))
        with temp_project({"shell.nix": "{ }\n", "default.nix": "{ }\n"}) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset({"Nix"}))
        with temp_project({"modules/shop.nix": "{ }\n"}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.build_systems), (NIX, frozenset()))

    def test_ci_usage(self) -> None:
        used = ("nix build", "nix-build default.nix", "statix check .", "uses: cachix/install-nix-action@v31")
        for text in (*used, "uses: DeterminateSystems/nix-installer-action@v23", "cachix push shop result"):
            with self.subTest(text=text):
                self.assertTrue(uses(NIX_ECOSYSTEM, text))
        for text in ("npm test", "make check"):
            with self.subTest(text=text):
                self.assertFalse(uses(NIX_ECOSYSTEM, text))


class NixTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, NIX_ECOSYSTEM)

    def test_the_flakes_checks_are_its_tests(self) -> None:
        for line in ("nix flake check", "nix flake check --all-systems", "nix build .#checks.x86_64-linux.default"):
            with self.subTest(line=line):
                self.assertEqual(run_in_layout(self, "Nix flake", tests_run, _ci(line)).status, Status.PASS)
        self.assertEqual(run_in_layout(self, "Nix flake", tests_run, _ci("nix build")).status, Status.WARN)
        self.assertEqual(run_in_layout(self, "Nix expressions", tests_run, _ci("nix flake check")).status, Status.FAIL)

    def test_the_formatters_check_or_apply(self) -> None:
        checks = ("nixfmt --check .", "nixpkgs-fmt --check .", "alejandra -c .", "nix fmt -- --check .")
        for line, tool in zip(checks, ("nixfmt", "nixfmt", "alejandra", "nix fmt"), strict=True):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.PASS)
                self.assertIn(f"CI enforces the {tool} style", self._run(code_formatting, _ci(line)).message)
        for line in ("nixfmt .", "alejandra .", "nix fmt"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)

    def test_statix_and_deadnix_are_the_lints_and_deadnix_fails_with_the_flag(self) -> None:
        both = _ci("statix check .", "deadnix --fail .")
        self.assertEqual(
            self._run(compiler_warnings, both), Result.passed("strict Nix lints are enabled: statix, deadnix")
        )
        self.assertEqual(
            self._run(warnings_as_errors, both),
            Result.passed(
                "warnings are treated as errors with statix check, which fails on any finding, deadnix --fail"
            ),
        )
        self.assertEqual(self._run(static_analysis, both), Result.passed("statix and deadnix run"))
        lax = _ci("statix check .", "deadnix .")
        self.assertEqual(self._run(compiler_warnings, lax).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, lax).status, Status.FAIL)
        self.assertEqual(self._run(compiler_warnings, _ci("statix check .")).status, Status.WARN)
        self.assertEqual(self._run(static_analysis, _ci("nix build")).status, Status.FAIL)

    def test_what_nix_runs_in_turn_is_what_the_tools_claim(self) -> None:
        for line in (
            "nix run nixpkgs#statix -- check .",
            "nix develop -c statix check .",
            "nix develop .#ci --command statix check .",
            "nix shell nixpkgs#statix -c statix check .",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)), Result.passed("statix runs"))
        # Without arguments to pass, or a command to run, nothing is claimed.
        for line in ("nix run nixpkgs#statix", "nix run", "nix develop", "nix develop .#ci -c", "nix shell nixpkgs#x"):
            with self.subTest(line=line):
                self.assertEqual(self._run(static_analysis, _ci(line)).status, Status.FAIL)

    def test_the_result_symlinks_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "result\nresult-*\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "/result*\n"}).status, Status.PASS)
        result = self._run(vcs_ignore, {".gitignore": "*.log\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("result", " ".join((result.message, *result.details)))

    def test_the_platform_matrix_counts_the_systems_built(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: NIX_MATRIX})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("3 system(s) (aarch64-darwin, aarch64-linux, x86_64-linux)", result.message)
        runner = self._run(platform_matrix, github_job("macos-latest", "nix build"))
        self.assertIn("1 system(s) (aarch64-darwin)", runner.message)
        self.assertIn("(runner default)", " ".join(runner.details))
        self.assertIn("0 system(s)", self._run(platform_matrix, github_job("windows-latest", "nix build")).message)
