"""The OCaml profile's rules, judged by the generic checks in the dune project and plain OCaml layouts."""

from __future__ import annotations

import unittest
from pathlib import Path

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.ocaml import DUNE_TEST_STANZAS, OCAML_ECOSYSTEM, _without, dune_profile, forms
from project_validator.facts import Setting
from tests.support import GITHUB_WORKFLOW, command, github_job, github_steps, make_context, run_as, temp_project

OCAML = frozenset({"OCaml"})
TEST_STANZA = {"test/dune": "(test\n (name test_shop)\n (libraries shop alcotest))\n", "test/test_shop.ml": ""}
DUNE_PROJECT = {"dune-project": "(lang dune 3.0)\n"}
OCAML_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            ocaml-compiler: ["4.14.x", "5.2"]
        steps:
          - uses: ocaml/setup-ocaml@v3
            with:
              ocaml-compiler: ${{ matrix.ocaml-compiler }}
          - run: opam exec -- dune build
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _stanzas(dune: str) -> list[tuple[str, object]]:
    """The test stanzas the reader finds in a dune file's text."""
    return [(found.key, found.value) for found in DUNE_TEST_STANZAS.read("dune", dune) if isinstance(found, Setting)]


class RecognitionTests(unittest.TestCase):
    def test_sources_grammars_and_build_files(self) -> None:
        with temp_project({"src/shop.ml": "", "src/shop.mli": "", "src/lexer.mll": "", "test/run.t": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, OCAML)
        self.assertEqual(structure.build_systems, frozenset())
        with temp_project({**DUNE_PROJECT, "shop.opam": "", "bin/dune": "", "bin/main.ml": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.build_systems, frozenset({"dune", "opam"}))
        self.assertEqual([unit.directory for unit in structure.units], ["."])

    def test_build_trees(self) -> None:
        with temp_project({**DUNE_PROJECT, "_build/log": "", "_opam/.opam-switch/x": "", "lib/_build/x": ""}) as root:
            self.assertTrue(is_build_tree(Path(root, "_build")))
            self.assertTrue(is_build_tree(Path(root, "_opam")))
            self.assertFalse(is_build_tree(Path(root, "lib", "_build")))

    def test_ci_usage(self) -> None:
        for text in ("dune build", "opam install . --deps-only", "ocamlfind ocamlopt", "uses: ocaml/setup-ocaml@v3"):
            with self.subTest(text=text):
                self.assertTrue(OCAML_ECOSYSTEM.used_by(text))
        self.assertFalse(OCAML_ECOSYSTEM.used_by("npm test"))

    def test_dune_profiles(self) -> None:
        for line, profile in (
            ("dune build", "dev"),
            ("dune test --profile release", "release"),
            ("dune build --release @install", "release"),
            ("dune build -p shop @install", "release"),
            ("dune build --profile=static", "static"),
            ("opam install .", None),
        ):
            with self.subTest(line=line):
                self.assertEqual(dune_profile(command(line)), profile)
        self.assertEqual(dune_profile(command("dune build", {"DUNE_PROFILE": "release"})), "release")

    def test_forms_of_a_dune_file(self) -> None:
        text = "; a comment (test)\n(library\n (name shop)\n (flags (:standard -w +a)))\n(tests (names a b))\n"
        self.assertEqual(forms(text, "flags"), ("(:standard -w +a)",))
        self.assertEqual(forms(text, "test"), ())
        self.assertEqual(forms(text, "tests"), ("(names a b)",))
        self.assertEqual(forms("(flags (:standard", "flags"), ())
        self.assertEqual(_without("(env (release (flags (-w -a)) (release)) (dev))", "release"), "(env  (dev))")
        self.assertEqual(_stanzas(text), [("tests", "a"), ("tests", "b")])
        inline = "(library\n (name shop)\n (inline_tests))\n(cram\n (deps %{bin:shop}))\n(test)\n"
        self.assertEqual(_stanzas(inline), [("test", "?"), ("inline_tests", True), ("cram", True)])


class OCamlTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, OCAML_ECOSYSTEM)

    def test_dune_runs_the_declared_tests(self) -> None:
        for line in (
            "dune test",
            "dune runtest",
            "dune build @runtest",
            "dune build @test/runtest",
            "opam exec -- dune test",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TEST_STANZA, **_ci(line)}).status, Status.PASS)
        inline = {"lib/dune": "(library\n (name shop)\n (inline_tests)\n (preprocess (pps ppx_expect)))\n"}
        self.assertEqual(self._run(tests_run, {**inline, **_ci("dune test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TEST_STANZA, **_ci("dune build")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("dune test")).status, Status.FAIL)

    def test_bisect_ppx_counts_branches(self) -> None:
        for line in (
            "dune test --instrument-with bisect_ppx",
            "dune runtest --instrument-with=landmarks,bisect_ppx --force",
            "bisect-ppx-report send-to Codecov",
        ):
            with self.subTest(line=line):
                result = self._run(coverage, _ci(line))
                self.assertEqual(result, Result.passed("branch coverage is reported with bisect_ppx"))
        legacy = github_job("ubuntu-latest", "BISECT_ENABLE=yes dune runtest")
        self.assertEqual(self._run(coverage, legacy).status, Status.PASS)
        self.assertEqual(self._run(coverage, _ci("dune test")).status, Status.FAIL)

    def test_ocamlformat_needs_its_file_and_a_check(self) -> None:
        style = {".ocamlformat": "version = 0.27.0\n"}
        for line in ("dune build @fmt", "dune build @lib/fmt", "ocamlformat --check lib/shop.ml"):
            with self.subTest(line=line):
                result = self._run(code_formatting, {**style, **_ci(line)})
                self.assertEqual(result, Result.passed(".ocamlformat is defined and CI runs ocamlformat"))
        self.assertEqual(self._run(code_formatting, _ci("dune build @fmt")).status, Status.FAIL)
        for line in ("dune fmt", "dune build @fmt --auto-promote"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, {**style, **_ci(line)}).status, Status.FAIL)
        # Plain ocamlformat prints the formatted code: it is not a formatter run.
        self.assertEqual(self._run(code_formatting, {**style, **_ci("ocamlformat lib/shop.ml")}).status, Status.WARN)

    def test_the_dev_profile_is_the_strict_warning_set(self) -> None:
        passed = Result.passed("strict OCaml warning settings are enabled: dune's dev profile warning set (or -w +a)")
        for line in (
            "dune build",
            "dune test --profile dev",
            "opam exec -- dune build @install",
            "ocamlfind ocamlopt -w +a -c shop.ml",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(compiler_warnings, _ci(line)), passed)
        for line in (
            "dune build --profile release",
            "dune build -p shop",
            "opam install .",
            "ocamlfind ocamlopt -c shop.ml",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(compiler_warnings, _ci(line)).status, Status.FAIL)

    def test_flags_that_drop_the_profiles_warnings(self) -> None:
        for flags in (
            "(flags (:standard -w +a-4))",
            "(env (release (flags (-w -a))))",
            "(flags (:standard -warn-error -a))",
        ):
            with self.subTest(flags=flags):
                files = {"lib/dune": f"(library\n (name shop)\n {flags})\n", **_ci("dune build")}
                self.assertEqual(self._run(compiler_warnings, files).status, Status.PASS)
        for flags in ("(flags (-w +a-4-9))", "(flags (:standard -w -a))", "(env (dev (flags (:standard -w -a+8))))"):
            with self.subTest(flags=flags):
                files = {"lib/dune": f"(library\n (name shop)\n {flags})\n", **_ci("dune build")}
                self.assertEqual(self._run(compiler_warnings, files).status, Status.FAIL)

    def test_the_dev_profile_makes_warnings_errors(self) -> None:
        passed = Result.passed("warnings are treated as errors with dune's dev profile (or -warn-error +a)")
        self.assertEqual(self._run(warnings_as_errors, _ci("dune build")), passed)
        self.assertEqual(self._run(warnings_as_errors, _ci("ocamlopt -warn-error +a -c shop.ml")), passed)
        self.assertEqual(self._run(warnings_as_errors, _ci("dune build --release")).status, Status.FAIL)
        dropped = {"dune": "(env\n (dev\n  (flags (:standard -warn-error -a))))\n", **_ci("dune build")}
        self.assertEqual(self._run(warnings_as_errors, dropped).status, Status.FAIL)
        kept = {"dune": "(env\n (dev\n  (flags (:standard -w +a-4))))\n", **_ci("dune build")}
        self.assertEqual(self._run(warnings_as_errors, kept).status, Status.PASS)

    def test_semgrep_reads_ocaml_and_codeql_does_not(self) -> None:
        semgrep = self._run(security_scanning, _ci("semgrep ci"))
        self.assertEqual(semgrep, Result.passed("CI scans the code for security problems with semgrep"))
        codeql = self._run(security_scanning, github_steps("uses: github/codeql-action/analyze@v3"))
        self.assertEqual(codeql.status, Status.WARN)

    def test_the_build_directory_and_the_local_switch_must_be_ignored(self) -> None:
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "_build/\n_opam/\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "/_build\n/_opam\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "_build/\n"}).status, Status.WARN)

    def test_the_platform_matrix_counts_compiler_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: OCAML_MATRIX})
        self.assertIn("2 OCaml version(s) (4.14.x, 5.2)", result.message)
        for line, version in (
            ("docker run ocaml/opam:debian-12-ocaml-5.1 dune build", "5.1"),
            ("opam switch create . ocaml-base-compiler.5.2.0", "5.2.0"),
            ("opam switch create 4.14.2", "4.14.2"),
            ("opam exec -- dune build", "default"),
        ):
            with self.subTest(line=line):
                self.assertIn(f"1 OCaml version(s) ({version})", self._run(platform_matrix, _ci(line)).message)
        steps = github_steps("uses: ocaml/setup-ocaml@v3", "run: dune build")
        steps[GITHUB_WORKFLOW] = steps[GITHUB_WORKFLOW].replace(
            '"uses": "ocaml/setup-ocaml@v3"',
            '"uses": "ocaml/setup-ocaml@v3", "with": {"ocaml-compiler": "ocaml-variants.5.3.0+options"}',
        )
        self.assertIn("1 OCaml version(s) (5.3.0)", self._run(platform_matrix, steps).message)
