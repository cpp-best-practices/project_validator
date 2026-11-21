"""Every spelling a reader accepts is tested: each alternative spelling of an option, program or subcommand reads the
same as its siblings and differently from leaving it out, and each action reader's defaults are pinned, so dropping
one can not go unnoticed (upstream #302)."""

from __future__ import annotations

import unittest
from collections.abc import Callable, Sequence

from project_validator.ecosystems.common_lisp import _run_tests_action
from project_validator.ecosystems.dart import _dart_format
from project_validator.ecosystems.docker.tools import _scout_action
from project_validator.ecosystems.documentation import _markdown_link_check_action
from project_validator.ecosystems.dotnet.tools import _nuget_audit
from project_validator.ecosystems.graphql import _graphql_inspector_action
from project_validator.ecosystems.haskell.tools import _hpc
from project_validator.ecosystems.javascript import _tasks
from project_validator.ecosystems.javascript.analysis import _tsconfig
from project_validator.ecosystems.julia import _runtest
from project_validator.ecosystems.jvm.fuzzing import _names_a_class_or_jar
from project_validator.ecosystems.kubernetes import _kube_linter_action
from project_validator.ecosystems.openapi import _oasdiff_action
from project_validator.ecosystems.r import _rcmdcheck
from project_validator.ecosystems.scala import _mill_scalafmt
from project_validator.ecosystems.sql import _squawk_action
from project_validator.ecosystems.tabular_data import _frictionless_action
from project_validator.facts import Command, Facts, Origin, Setting
from project_validator.tools.audits import _trivy_action
from project_validator.tools.coverage import _lcov, _llvm_cov
from tests.support import command


class AliasTestCase(unittest.TestCase):
    def assert_spellings(
        self, read: Callable[[Command], object], spellings: Sequence[str], *, unlike: str | None = None
    ) -> None:
        """Every one of `spellings` reads the same, and differently from `unlike` (the spelling left out)."""
        first = read(command(spellings[0]))
        for line in spellings[1:]:
            with self.subTest(line=line):
                self.assertEqual(read(command(line)), first)
        if unlike is not None:
            self.assertNotEqual(read(command(unlike)), first, unlike)


def _with_facts(claim: Callable[[Command, Facts], object], facts: Facts | None = None) -> Callable[[Command], object]:
    return lambda found: claim(found, facts or Facts())


class CoverageSpellingTests(AliasTestCase):
    def test_lcov_reports_with_genhtml_list_or_summary(self) -> None:
        read = _with_facts(_lcov)
        self.assert_spellings(
            read,
            ["genhtml out.info", "lcov --list out.info", "lcov -l out.info", "lcov --summary out.info"],
            unlike="lcov --capture -o out.info",
        )
        self.assert_spellings(read, ["geninfo .", "lcov --capture -o out.info"])

    def test_lcov_counts_branches_and_conditions_by_option_or_rc(self) -> None:
        read = _with_facts(_lcov)
        self.assert_spellings(
            read, ["lcov --capture --branch-coverage", "lcov --capture --rc branch_coverage=1"], unlike="lcov --capture"
        )
        self.assert_spellings(
            read, ["lcov --capture --mcdc-coverage", "lcov --capture --rc mcdc_coverage=1"], unlike="lcov --capture"
        )

    def test_llvm_cov_options_in_either_dash_form(self) -> None:
        read = _with_facts(_llvm_cov)
        self.assert_spellings(
            read,
            ["llvm-cov show -show-branches=count x", "llvm-cov show --show-branches=count x"],
            unlike="llvm-cov show x",
        )
        self.assert_spellings(
            read,
            [
                "llvm-cov report -show-mcdc x",
                "llvm-cov report --show-mcdc x",
                "llvm-cov report -show-mcdc-summary x",
                "llvm-cov report --show-mcdc-summary x",
            ],
            unlike="llvm-cov report x",
        )


class CommandSpellingTests(AliasTestCase):
    def test_tsc_names_its_configuration_with_any_project_or_build_option(self) -> None:
        self.assert_spellings(
            _tsconfig,
            [
                *("tsc -p app/tsconfig.json", "tsc --project app/tsconfig.json", "tsc -b app/tsconfig.json"),
                *("tsc --build app/tsconfig.json", "tsc -p app"),
            ],
            unlike="tsc",
        )

    def test_the_jvm_jazzer_names_a_class_classpath_or_jar(self) -> None:
        self.assert_spellings(
            _names_a_class_or_jar,
            ["jazzer --target_class=a.B", "jazzer --cp=x", "jazzer -cp x", "jazzer --classpath=x", "jazzer t.jar"],
            unlike="jazzer fuzz.js",
        )

    def test_nuget_audits_on_any_restore(self) -> None:
        audit = Setting(origin=Origin(path="Directory.Build.props"), tool="MSBuild", key="NuGetAuditMode", value="All")
        self.assert_spellings(
            _with_facts(_nuget_audit, Facts([audit])),
            ["msbuild -restore", "MSBuild -restore", "dotnet restore", "dotnet build"],
            unlike="dotnet format",
        )

    def test_mill_checks_formatting_with_either_task(self) -> None:
        self.assert_spellings(
            _with_facts(_mill_scalafmt),
            ["mill __.checkFormat", "mill mill.scalalib.scalafmt.ScalafmtModule/checkFormatAll"],
        )

    def test_dart_format_only_shows_with_either_output_option(self) -> None:
        self.assert_spellings(
            _with_facts(_dart_format),
            [
                "dart format --output none .",
                "dart format -o none .",
                "dart format --output json .",
                "dart format -o show .",
            ],
            unlike="dart format .",
        )

    def test_dart_format_only_shows_with_the_output_option_joined_to_its_value(self) -> None:
        self.assert_spellings(
            _with_facts(_dart_format),
            ["dart format --output none .", "dart format --output=none .", "dart format -o=show ."],
        )

    def test_haskell_coverage_with_either_flag_on_any_build(self) -> None:
        self.assert_spellings(
            _with_facts(_hpc),
            [
                *("cabal test --enable-coverage", "cabal test --coverage", "cabal build --enable-coverage"),
                "cabal run --coverage",
            ],
            unlike="cabal test",
        )


class TaskRunnerTests(unittest.TestCase):
    def test_the_tasks_each_runner_runs(self) -> None:
        cases = [
            ("nx", ["run-many"], {"-t": "test,lint"}, ["test", "lint"]),
            ("nx", ["run-many"], {"--target": "test"}, ["test"]),
            ("nx", ["run-many"], {"--targets": "test,,lint"}, ["test", "lint"]),
            ("nx", ["affected"], {"-t": "test"}, ["test"]),
            ("nx", ["affected", "x"], {"-t": "test"}, ["test"]),
            # nx runs a target only with run-many or affected, and only one that is named.
            ("nx", ["graph"], {"-t": "test"}, []),
            ("nx", ["run-many"], {}, []),
            ("turbo", ["run", "a", "b"], {}, ["a", "b"]),
            ("turbo", ["a", "b"], {}, ["a", "b"]),
            ("lerna", ["run", "a"], {}, ["a"]),
            # lerna's other commands (`lerna version`) run no task.
            ("lerna", ["version"], {}, []),
        ]
        for runner, words, options, expected in cases:
            with self.subTest(runner=runner, words=words, options=options):
                self.assertEqual(_tasks(runner, words, options), expected)


ACTION_INPUTS: tuple[tuple[Callable[[dict[str, str]], object], dict[str, str], object], ...] = (
    (_markdown_link_check_action, {"folder-path": "docs"}, (("markdown-link-check", "docs"),)),
    (_run_tests_action, {"asdf-system": "app"}, (("ros", "run", "--eval", "(asdf:test-system :app)"),)),
    (_run_tests_action, {"run-tests": "(app:run)"}, (("ros", "run", "--eval", "(app:run)"),)),
    (_oasdiff_action, {"base": "a.yaml", "revision": "b.yaml"}, (("oasdiff", "breaking", "a.yaml", "b.yaml"),)),
    (
        _scout_action,
        {"command": "cves, recommendations", "image": "app:1"},
        (
            ("docker", "scout", "cves", "app:1"),
            ("docker", "scout", "recommendations", "app:1"),
        ),
    ),
    *(
        (_frictionless_action, {name: f"{name}/*"}, (("frictionless", "validate", f"{name}/*"),))
        for name in ("inquiry", "packages", "resources", "tables")
    ),
    (
        _frictionless_action,
        {"packages": "a.json", "tables": "t/*.csv", "resources": ""},
        (("frictionless", "validate", "a.json", "t/*.csv"),),
    ),
    (_trivy_action, {}, (("trivy", "image", "."),)),
    (_trivy_action, {"image-ref": "app:1", "scan-ref": "src"}, (("trivy", "image", "app:1"),)),
    (_trivy_action, {"scan-type": "fs", "image-ref": "app:1", "scan-ref": "src"}, (("trivy", "fs", "src"),)),
    (_trivy_action, {"scan-type": "fs", "scanners": "vuln"}, (("trivy", "fs", "--scanners", "vuln", "."),)),
    (_trivy_action, {"scan-type": "vm"}, ()),
    (
        _kube_linter_action,
        {"config": "k.yaml", "directory": "charts"},
        (("kube-linter", "lint", "--config", "k.yaml", "charts"),),
    ),
    (_graphql_inspector_action, {}, (("graphql-inspector", "diff"),)),
    (
        _graphql_inspector_action,
        {"schema": "main:schema.graphql"},
        (("graphql-inspector", "diff", "main:schema.graphql"),),
    ),
    (_graphql_inspector_action, {"schema": "main:s.graphql", "fail-on-breaking": " False "}, ()),
    (
        _rcmdcheck,
        {"args": 'c("--no-manual")', "error-on": '"error"'},
        (("Rscript", "-e", 'rcmdcheck::rcmdcheck(args = (c("--no-manual")), error_on = ("error"))'),),
    ),
    (
        _runtest,
        {"coverage": "FALSE", "depwarn": "error"},
        (("julia", "--color=yes", "--depwarn=error", "-e", "using Pkg; Pkg.test()"),),
    ),
    (
        _run_tests_action,
        {"asdf-system": "app", "coveralls-token": "t"},
        (("ros", "run", "--eval", "(require :sb-cover)", "--eval", "(asdf:test-system :app)"),),
    ),
    # squawk-action fails the job only when told to (any case), on its files, else its pattern.
    (_squawk_action, {"fail-on-violations": "true"}, (("squawk", "migrations/*.sql"),)),
    (_squawk_action, {"fail-on-violations": " TRUE "}, (("squawk", "migrations/*.sql"),)),
    (_squawk_action, {"fail-on-violations": "yes"}, ()),
    (_squawk_action, {"fail-on-violations": "true", "pattern": "db/*.sql"}, (("squawk", "db/*.sql"),)),
    (_squawk_action, {"fail-on-violations": "true", "files": "a.sql b.sql"}, (("squawk", "a.sql", "b.sql"),)),
)


class ActionDefaultTests(unittest.TestCase):
    def test_each_action_reader_s_defaults(self) -> None:
        rcmdcheck = 'rcmdcheck::rcmdcheck(args = (c("--no-manual", "--as-cran")), error_on = ("warning"))'
        cases = {
            _oasdiff_action: (("oasdiff", "breaking", "", ""),),
            _scout_action: (("docker", "scout", "quickview", ""),),
            _squawk_action: (),
            _frictionless_action: (("frictionless", "validate", "datapackage.json"),),
            _kube_linter_action: (("kube-linter", "lint", "."),),
            _rcmdcheck: (("Rscript", "-e", rcmdcheck),),
            _markdown_link_check_action: (("markdown-link-check", "."),),
            _runtest: (
                ("julia", "--color=yes", "--depwarn=yes", "--code-coverage=user", "-e", "using Pkg; Pkg.test()"),
            ),
            _run_tests_action: (("ros", "run", "--eval", "(asdf:test-system)"),),
        }
        for read, expected in cases.items():
            with self.subTest(read=read.__name__):
                self.assertEqual(read({}), expected)

    def test_each_action_reader_s_inputs(self) -> None:
        for read, inputs, expected in ACTION_INPUTS:
            with self.subTest(read=read.__name__, inputs=inputs):
                self.assertEqual(read(inputs), expected)


if __name__ == "__main__":
    unittest.main()
