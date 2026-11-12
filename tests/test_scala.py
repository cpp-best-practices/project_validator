"""The Scala profile's rules, judged by the generic checks in the sbt, Mill and scala-cli project layouts."""

from __future__ import annotations

import json
import unittest

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
from project_validator.ecosystems.scala import SCALA_ECOSYSTEM, mill_tasks, sbt_tasks, scala_cli_command
from tests.support import (
    GITHUB_WORKFLOW,
    github_job,
    github_steps,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
    uses,
)

SCALAFMT = {".scalafmt.conf": "version = 3.8.6\nrunner.dialect = scala3\n"}
SCALAFIX = {".scalafix.conf": "rules = [DisableSyntax]\n"}
MUNIT = {"src/test/scala/ShopSuite.scala": 'class ShopSuite extends munit.FunSuite:\n  test("adds") {}\n'}
SCALATEST = {
    "src/test/scala/ShopSpec.scala": "import org.scalatest.flatspec.AnyFlatSpec\n\nclass ShopSpec extends AnyFlatSpec\n"
}
STRICT_BUILD = {"build.sbt": 'scalacOptions ++= Seq("-deprecation", "-feature", "-Xlint", "-Werror")\n'}
JDK_SCALA_MATRIX = """\
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest]
            java: ["17", "21"]
            scala: ["2.13.16", "3.3.5"]
        steps:
          - uses: actions/setup-java@v4
            with:
              java-version: ${{ matrix.java }}
          - run: sbt ++${{ matrix.scala }} test
    """


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class TaskParsingTests(unittest.TestCase):
    def test_sbt_tasks_in_words_quoted_words_and_scopes(self) -> None:
        self.assertEqual(sbt_tasks(("sbt", "-Dsbt.ci=true", "--client", "coverage", "test")), ("coverage", "test"))
        self.assertEqual(
            sbt_tasks(("sbt", "++3.3.5", "scalafixAll --check", "; core/test ; Test/scalafmtCheck", "+publishLocal")),
            ("scalafixAll", "--check", "test", "scalafmtCheck", "publishLocal"),
        )
        self.assertEqual(sbt_tasks(("sbt", "--java-home", "/opt/jdk", "project", "core", "compile")), ("compile",))
        self.assertEqual(sbt_tasks(("sbt",)), ())
        self.assertEqual(sbt_tasks(("mill", "__.test")), ())

    def test_mill_tasks_are_selectors_with_their_arguments(self) -> None:
        self.assertEqual(mill_tasks(("mill", "-i", "-j", "0", "__.test")), ((("__", "test"), ()),))
        self.assertEqual(
            mill_tasks(("mill", "__.fix", "--check", "+", "__.scoverage.xmlReport")),
            ((("__", "fix"), ("--check",)), (("__", "scoverage", "xmlReport"), ())),
        )
        self.assertEqual(
            mill_tasks(("mill", "mill.scalalib.scalafmt.ScalafmtModule/checkFormatAll", "__.sources")),
            ((("mill", "scalalib", "scalafmt", "ScalafmtModule", "checkFormatAll"), ("__.sources",)),),
        )
        self.assertEqual(mill_tasks(("sbt", "test")), ())

    def test_scala_cli_and_the_scala_runner(self) -> None:
        self.assertEqual(scala_cli_command(("scala-cli", "--power", "fmt", "--check", ".")), ("fmt", "--check", "."))
        self.assertEqual(scala_cli_command(("scala", "test", ".")), ("test", "."))
        self.assertEqual(scala_cli_command(("scala", "Main.scala")), ())
        self.assertEqual(scala_cli_command(("scalac", "Main.scala")), ())


class RecognitionTests(unittest.TestCase):
    def test_scripts_are_scala_once_the_project_is(self) -> None:
        with temp_project({"script.sc": "println(1)\n"}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset())
        self.assertEqual(structure.unrecognised_suffixes, ((".sc", 1),))
        with temp_project({"build.sbt": "", "script.sc": "", "project/plugins.sbt": ""}) as root:
            structure = make_context(root).structure
        self.assertEqual(structure.languages, frozenset({"Scala"}))
        self.assertEqual(structure.build_systems, frozenset({"sbt"}))
        self.assertEqual(structure.unrecognised_suffixes, ())

    def test_build_trees_are_the_build_tools_output_directories_only(self) -> None:
        sbt = {"build.sbt": "", "src/main/scala/A.scala": "", "target/A.class": "", "project/target/B.class": ""}
        with temp_project(sbt) as root:
            files = set(make_context(root).project.files())
        self.assertEqual({path for path in files if "target" in path}, set())
        mill = {"build.mill": "", "shop/src/A.scala": "", "out/A.class": "", "target/A.class": ""}
        with temp_project(mill) as root:
            files = set(make_context(root).project.files())
        self.assertEqual({path for path in files if path.endswith(".class")}, {"target/A.class"})
        # Another ecosystem's target directory is not sbt's.
        with temp_project({"dbt_project.yml": "", "target/manifest.json": ""}) as root:
            self.assertIn("target/manifest.json", make_context(root).project.files())

    def test_ci_usage(self) -> None:
        for text in (
            "sbt test",
            "./mill __.test",
            "scala-cli test .",
            "uses: sbt/setup-sbt@v1",
            "uses: coursier/setup-action@v1",
        ):
            with self.subTest(text=text):
                self.assertTrue(uses(SCALA_ECOSYSTEM, text))
        self.assertFalse(uses(SCALA_ECOSYSTEM, "mvn verify"))


class ScalaTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, SCALA_ECOSYSTEM)

    def test_suites_run_by_sbt_mill_or_scala_cli(self) -> None:
        for command in (
            "sbt test",
            "sbt +test",
            "sbt core/testOnly shop.ShopSuite",
            "mill __.test",
            "scala-cli test .",
            "scala test .",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._run(tests_run, {**MUNIT, **_ci(command)}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**SCALATEST, **_ci("sbt test")}).status, Status.PASS)
        mill_layout = {"shop/test/src/ShopSuite.scala": "import utest._\n\nobject ShopSuite extends TestSuite\n"}
        self.assertEqual(self._run(tests_run, {**mill_layout, **_ci("mill __.test")}).status, Status.PASS)
        self.assertEqual(self._run(tests_run, {**MUNIT, **_ci("sbt compile")}).status, Status.WARN)
        helper = {"src/test/scala/Fixtures.scala": "object Fixtures\n", **_ci("sbt test")}
        self.assertEqual(self._run(tests_run, helper).status, Status.FAIL)

    def test_scoverage_reports_branches_when_it_reports(self) -> None:
        for command in (
            "sbt coverage test coverageReport",
            "sbt coverage test coverageAggregate",
            "mill __.scoverage.xmlReport",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(coverage, _ci(command)), Result.passed("branch coverage is reported with scoverage")
                )
        self.assertEqual(self._run(coverage, _ci("sbt coverage test")).status, Status.FAIL)
        self.assertEqual(
            self._run(coverage, _ci("sbt jacoco")), Result.passed("branch coverage is reported with sbt-jacoco")
        )

    def test_scalafmt_needs_its_configuration_and_a_checking_run(self) -> None:
        for command in (
            "sbt scalafmtCheckAll scalafmtSbtCheck",
            "sbt Test/scalafmtCheck",
            "scalafmt --check",
            "scalafmt --test",
            "scala-cli fmt --check .",
        ):
            with self.subTest(command=command):
                result = self._run(code_formatting, {**SCALAFMT, **_ci(command)})
                self.assertEqual(result, Result.passed(".scalafmt.conf is defined and CI runs scalafmt"))
        self.assertEqual(self._run(code_formatting, {**SCALAFMT, **_ci("mill __.checkFormat")}).status, Status.PASS)
        for command in ("sbt scalafmtAll", "scalafmt", "scala-cli fmt .", "mill __.reformat"):
            with self.subTest(command=command):
                self.assertEqual(self._run(code_formatting, {**SCALAFMT, **_ci(command)}).status, Status.FAIL)
        result = self._run(code_formatting, _ci("sbt scalafmtCheckAll"))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("no scalafmt configuration", result.message)

    def test_the_warning_options_or_sbt_tpolecat_are_the_strict_set(self) -> None:
        result = self._run(compiler_warnings, STRICT_BUILD)
        self.assertEqual(
            result,
            Result.passed("strict scalac warning options are enabled: -deprecation, -feature, -Xlint or -Wunused"),
        )
        scala3 = {
            "build.mill": "object shop extends ScalaModule {\n"
            '  def scalacOptions = Seq("-deprecation", "-feature", "-Wunused:all")\n}\n'
        }
        self.assertEqual(self._run(compiler_warnings, scala3).status, Status.PASS)
        directives = {"project.scala": "//> using scala 3.3.5\n//> using options -deprecation -feature -Wall\n"}
        self.assertEqual(self._run(compiler_warnings, directives).status, Status.PASS)
        tpolecat = {"project/plugins.sbt": 'addSbtPlugin("org.typelevel" % "sbt-tpolecat" % "0.5.2")\n'}
        self.assertEqual(self._run(compiler_warnings, tpolecat).status, Status.PASS)
        some = {"build.sbt": 'scalacOptions += "-deprecation"\n'}
        result = self._run(compiler_warnings, some)
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.message, "missing scalac warning options: -feature, -Xlint or -Wunused")

    def test_warnings_as_errors_in_the_build_or_tpolecats_ci_mode(self) -> None:
        self.assertEqual(self._run(warnings_as_errors, STRICT_BUILD).status, Status.PASS)
        self.assertEqual(
            self._run(warnings_as_errors, {"build.sbt": 'scalacOptions += "-Xfatal-warnings"\n'}).status, Status.PASS
        )
        ci_mode = {
            GITHUB_WORKFLOW: json.dumps(
                {
                    "jobs": {
                        "build": {
                            "runs-on": "ubuntu-latest",
                            "env": {"SBT_TPOLECAT_CI": "true"},
                            "steps": [{"run": "sbt test"}],
                        }
                    }
                }
            )
        }
        self.assertEqual(self._run(warnings_as_errors, ci_mode).status, Status.PASS)
        mode = {"build.sbt": "ThisBuild / tpolecatDefaultOptionsMode := CiMode\n"}
        self.assertEqual(self._run(warnings_as_errors, mode).status, Status.PASS)
        self.assertEqual(self._run(warnings_as_errors, _ci("sbt test")).status, Status.FAIL)

    def test_scalafix_runs_the_rules_its_configuration_names(self) -> None:
        for command in ('sbt "scalafixAll --check"', "sbt scalafix", "mill __.fix --check"):
            with self.subTest(command=command):
                result = self._run(static_analysis, {**SCALAFIX, **_ci(command)})
                self.assertEqual(result, Result.passed("scalafix (.scalafix.conf) runs"))
        without_rules = self._run(static_analysis, _ci('sbt "scalafixAll --check"'))
        self.assertEqual(without_rules.status, Status.WARN)
        self.assertIn("no configuration of its checks", without_rules.message)
        self.assertEqual(self._run(static_analysis, {**SCALAFIX, **_ci("sbt test")}).status, Status.WARN)

    def test_semgrep_scans_but_codeql_does_not(self) -> None:
        self.assertEqual(
            self._run(security_scanning, _ci("semgrep scan --config p/scala --error .")).status, Status.PASS
        )
        self.assertEqual(
            self._run(security_scanning, github_steps("uses: github/codeql-action/analyze@v3")).status, Status.WARN
        )

    def test_dependency_check_snyk_but_not_osv_scanner_audit(self) -> None:
        for command in ("sbt dependencyCheck", "sbt dependencyCheckAggregate", "snyk test"):
            with self.subTest(command=command):
                self.assertEqual(self._run(dependency_audit, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(dependency_audit, _ci("osv-scanner -r .")).status, Status.WARN)

    # A committed output is judged in the bare fixture: in a project that is no repository, a build tree is never read.
    def test_each_build_tool_has_its_output_directory(self) -> None:
        for layout, directory, other in (
            ("sbt Scala", "target", "out"),
            ("Mill Scala", "out", "target"),
            ("scala-cli Scala", ".scala-build", "target"),
        ):
            with self.subTest(layout=layout):
                self.assertEqual(
                    run_in_layout(self, layout, vcs_ignore, {".gitignore": f"{directory}/\n"}).status, Status.PASS
                )
                self.assertEqual(
                    run_in_layout(self, layout, vcs_ignore, {".gitignore": f"{other}/\n"}).status, Status.WARN
                )

    def test_the_platform_matrix_pairs_jdks_with_the_scala_versions_switched_to(self) -> None:
        result = self._run(platform_matrix, {GITHUB_WORKFLOW: JDK_SCALA_MATRIX})
        self.assertIn(
            "4 JDK or Scala version(s) (JDK 17 / Scala 2.13.16, JDK 17 / Scala 3.3.5, JDK 21 / Scala 2.13.16, "
            "JDK 21 / Scala 3.3.5)",
            result.message,
        )
        coursier = github_steps("uses: coursier/setup-action@v1", "run: sbt test")
        coursier[GITHUB_WORKFLOW] = coursier[GITHUB_WORKFLOW].replace(
            '"uses": "coursier/setup-action@v1"',
            '"uses": "coursier/setup-action@v1", "with": {"jvm": "temurin:21", "apps": "sbt"}',
        )
        self.assertIn("1 JDK or Scala version(s) (JDK 21)", self._run(platform_matrix, coursier).message)
        scala_only = _ci("scala-cli --scala 3.3.5 test .")
        self.assertIn("(Scala 3.3.5)", self._run(platform_matrix, scala_only).message)
        self.assertIn("(default)", self._run(platform_matrix, _ci("sbt test")).message)
