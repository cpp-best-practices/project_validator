"""The Clojure profile's rules, judged by the generic checks in the deps.edn, Leiningen and Clojure sources layouts."""

import unittest
from pathlib import Path

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems import is_build_tree
from project_validator.ecosystems.clojure import CLOJURE_ECOSYSTEM, cli_aliases
from tests.support import (
    GITHUB_WORKFLOW,
    command,
    github_job,
    github_steps,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
)

CLOJURE = frozenset({"Clojure"})
TESTS = {"test/shop/core_test.clj": "(ns shop.core-test (:require [clojure.test :refer [deftest is]]))\n(deftest t)\n"}
REFLECTION = {"src/shop/warn.clj": "(ns shop.warn)\n(set! *warn-on-reflection* true)\n"}
JDK_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, macos-latest]
            java: ["17", "21"]
        steps:
          - uses: actions/setup-java@v4
            with:
              java-version: ${{ matrix.java }}
          - uses: DeLaGuardo/setup-clojure@13.7
            with:
              cli: latest
          - run: clojure -M:test
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_sources_and_the_build_files(self) -> None:
        files = {
            "deps.edn": "{}",
            "bb.edn": "{}",
            "src/shop/core.cljc": "",
            "src/shop/ui.cljs": "",
            "tests.edn": "{}",
            "tasks.bb": "",
        }
        with temp_project(files) as root:
            structure = make_context(root).structure
        self.assertEqual(
            (structure.languages, structure.build_systems), (CLOJURE, frozenset({"Clojure CLI", "Babashka"}))
        )
        self.assertEqual(structure.unrecognised_suffixes, ())
        with temp_project({"shadow-cljs.edn": "{}", "project.clj": "", "src/shop/core.clj": ""}) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset({"shadow-cljs", "Leiningen"}))

    def test_build_trees(self) -> None:
        files = {
            "deps.edn": "{}",
            ".cpcache/x": "",
            "target/classes/x": "",
            ".shadow-cljs/x": "",
            "src/target/x.clj": "",
        }
        with temp_project(files) as root:
            for name in (".cpcache", "target", ".shadow-cljs"):
                self.assertTrue(is_build_tree(Path(root, name)), name)
            self.assertFalse(is_build_tree(Path(root, "src", "target")))

    def test_the_aliases_a_cli_command_runs(self) -> None:
        self.assertEqual(cli_aliases(command("clojure -M:test:dev -m kaocha.runner").argv), frozenset({"test", "dev"}))
        self.assertEqual(cli_aliases(command("clj -X:build test").argv), frozenset({"build"}))
        self.assertEqual(cli_aliases(command("clojure -T:build jar").argv), frozenset({"build"}))
        self.assertEqual(cli_aliases(command("lein test").argv), frozenset())

    def test_ci_usage(self) -> None:
        for text in (
            "clojure -M:test",
            "lein test",
            "bb test",
            "uses: DeLaGuardo/setup-clojure@13.7",
            "clj-kondo --lint src",
        ):
            with self.subTest(text=text):
                self.assertTrue(CLOJURE_ECOSYSTEM.used_by(text))
        self.assertFalse(CLOJURE_ECOSYSTEM.used_by("npm test"))


class ClojureTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, CLOJURE_ECOSYSTEM)

    def test_the_runners_run_the_tests(self) -> None:
        for line in (
            "clojure -M:test",
            "clojure -X:test",
            "clj -M:kaocha",
            "lein test",
            "lein kaocha",
            "bb test",
            "bin/kaocha",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(tests_run, {**TESTS, **_ci(line)}).status, Status.PASS)
        speclj = {"spec/shop/core_spec.clj": '(describe "total" (it "sums" (should= 3 (total [1 2]))))\n'}
        self.assertEqual(self._run(tests_run, {**speclj, **_ci("lein spec")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**TESTS, **_ci("clojure -T:build jar")}).status, Status.WARN)
        self.assertEqual(self._run(tests_run, _ci("clojure -M:test")).status, Status.FAIL)

    def test_cloverage_counts_forms(self) -> None:
        passed = Result.passed("statement coverage is reported with cloverage")
        for line in (
            "lein cloverage --codecov",
            "clojure -M:coverage",
            "clojure -M:test:cov",
            "clojure -M:cloverage -p src -s test",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(coverage, _ci(line)), passed)
        self.assertEqual(self._run(coverage, _ci("clojure -M:test")).status, Status.FAIL)

    def test_the_formatters(self) -> None:
        for line in (
            "cljfmt check",
            "lein cljfmt check",
            "clojure -M:cljfmt check",
            "cljstyle check",
            "zprint --check src/shop/core.clj",
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.PASS)
        styled = {".cljfmt.edn": "{}", **_ci("cljfmt check")}
        self.assertEqual(self._run(code_formatting, styled).message, ".cljfmt.edn is defined and CI runs cljfmt")
        for line in ("cljfmt fix", "clojure -M:cljfmt fix", "cljstyle fix", "zprint -w src/shop/core.clj"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("clojure -M:cljfmt")).status, Status.FAIL)

    def test_clj_kondo_and_warn_on_reflection_are_the_warning_set(self) -> None:
        passed = Result.passed("strict Clojure lints are enabled: clj-kondo, *warn-on-reflection*")
        self.assertEqual(self._run(compiler_warnings, {**REFLECTION, **_ci("clj-kondo --lint src test")}), passed)
        globals_ = {"project.clj": '(defproject shop "0.1" :global-vars {*warn-on-reflection* true})\n'}
        self.assertEqual(
            run_in_layout(self, "Leiningen project", compiler_warnings, {**globals_, **_ci("lein clj-kondo")}), passed
        )
        partial = self._run(compiler_warnings, _ci("clojure -M:clj-kondo --lint src"))
        self.assertEqual(partial, Result.warned("missing Clojure lints: *warn-on-reflection*", "found clj-kondo"))
        # Installing clj-kondo is not running it.
        installing = github_steps("uses: DeLaGuardo/setup-clojure@13.7", "run: clojure -M:test")
        installing[GITHUB_WORKFLOW] = installing[GITHUB_WORKFLOW].replace(
            '"uses": "DeLaGuardo/setup-clojure@13.7"',
            '"uses": "DeLaGuardo/setup-clojure@13.7", "with": {"clj-kondo": "latest"}',
        )
        self.assertEqual(self._run(compiler_warnings, {**REFLECTION, **installing}).status, Status.WARN)

    def test_clj_kondo_fails_on_warnings_unless_told_otherwise(self) -> None:
        passed = Result.passed("warnings are treated as errors with clj-kondo failing on warnings")
        self.assertEqual(self._run(warnings_as_errors, _ci("clj-kondo --lint src test")), passed)
        self.assertEqual(
            self._run(warnings_as_errors, _ci("clj-kondo --lint src --fail-level error")).status, Status.FAIL
        )
        self.assertEqual(self._run(warnings_as_errors, _ci("clojure -M:test")).status, Status.FAIL)

    def test_clj_kondo_is_the_analyzer_and_nvd_the_auditor(self) -> None:
        configured = {".clj-kondo/config.edn": "{:linters {}}\n", **_ci("clj-kondo --lint src")}
        self.assertEqual(
            self._run(static_analysis, configured), Result.passed("clj-kondo (.clj-kondo/config.edn) runs")
        )
        self.assertEqual(self._run(static_analysis, _ci("lein test")).status, Status.FAIL)
        for line in ("clojure -M:nvd", "lein nvd check", "clj-watson scan -p deps.edn"):
            with self.subTest(line=line):
                self.assertEqual(self._run(dependency_audit, _ci(line)).status, Status.PASS)

    def test_semgrep_reads_clojure_and_codeql_does_not(self) -> None:
        codeql = github_steps("uses: github/codeql-action/analyze@v3")
        self.assertIn("semgrep", self._run(security_scanning, _ci("semgrep ci")).message)
        self.assertEqual(self._run(security_scanning, codeql).status, Status.WARN)

    def test_the_outputs_of_each_build_system_must_be_ignored(self) -> None:
        cli = {".gitignore": ".cpcache/\ntarget/\n.nrepl-port\n"}
        self.assertEqual(run_in_layout(self, "deps.edn project", vcs_ignore, cli).status, Status.PASS)
        result = run_in_layout(self, "deps.edn project", vcs_ignore, {".gitignore": "target/\n.nrepl-port\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn(".cpcache/", " ".join((result.message, *result.details)))
        lein = {".gitignore": "target/\n.nrepl-port\n"}
        self.assertEqual(run_in_layout(self, "Leiningen project", vcs_ignore, lein).status, Status.PASS)
        self.assertEqual(
            run_in_layout(self, "Clojure sources", vcs_ignore, {".gitignore": ".nrepl-port\n"}).status, Status.PASS
        )
        self.assertEqual(
            run_in_layout(self, "Clojure sources", vcs_ignore, {".gitignore": "target/\n"}).status, Status.WARN
        )

    def test_the_platform_matrix_counts_jdk_versions(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: JDK_MATRIX})
        self.assertIn("2 JDK version(s) (17, 21)", result.message)
        self.assertIn("1 JDK version(s) (default)", self._run(platform_matrix, _ci("lein test")).message)
