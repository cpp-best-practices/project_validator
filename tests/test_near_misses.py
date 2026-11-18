"""Recognisers shown what they must reject as well as what they accept: the lookalike programs, fixing runs and
disabling settings that would otherwise credit a project with a practice it does not have (upstream #301)."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.ci.github_expressions import Known, evaluate
from project_validator.ecosystems.beam import MIX_FORMAT
from project_validator.ecosystems.clojure import CLJFMT
from project_validator.ecosystems.dotnet.tools import _security_analysis
from project_validator.ecosystems.julia import _bounded
from project_validator.facts import Facts, Origin, Setting
from project_validator.facts.dependencies import Locked
from project_validator.facts.formatting import FORMAT, Enforcement, _keeps
from project_validator.facts.tools import Run
from project_validator.tools.audits import _gitlab_dependency_scanning
from tests.support import command

CHECKS = {FORMAT: frozenset({str(Enforcement.CHECK)})}
APPLIES = {FORMAT: frozenset({str(Enforcement.APPLY)})}


def _provided(run: Run | None) -> Mapping[str, frozenset[str]] | None:
    return None if run is None else run.provides


class GitDiffEnforcementTests(unittest.TestCase):
    def test_what_each_git_command_does_with_changes(self) -> None:
        cases = {
            "git diff --exit-code": True,
            "git diff --quiet": True,
            "git commit -am 'format'": True,
            "git diff": False,
            "git diff --stat": False,
            "git status --porcelain": False,
            "git status -s": False,
            "git status": None,
            "git log --oneline": None,
            "git": None,
            "hg diff --exit-code": None,
            "diff --exit-code a b": None,
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertIs(_keeps(command(line)), expected)


class GitlabDependencyScanningTests(unittest.TestCase):
    def test_only_the_dependency_scanning_template_audits(self) -> None:
        template = command("gitlab-template Security/Dependency-Scanning.gitlab-ci.yml")
        self.assertIsNotNone(_gitlab_dependency_scanning(template, Facts()))
        for line in (
            "gitlab-template Security/SAST.gitlab-ci.yml",
            "echo Security/Dependency-Scanning.gitlab-ci.yml",
            "gitlab-template",
        ):
            with self.subTest(line=line):
                self.assertIsNone(_gitlab_dependency_scanning(command(line), Facts()))


class FormatterModeTests(unittest.TestCase):
    def test_mix_format_checks_applies_or_only_lists(self) -> None:
        cases = {
            "mix format --check-formatted": CHECKS,
            "mix format": APPLIES,
            "mix format lib/app.ex": APPLIES,
            "mix format --dry-run": None,
            "mix test": None,
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(_provided(MIX_FORMAT.claims(command(line), Facts())), expected)

    def test_cljfmt_through_a_cli_alias_says_what_by_the_word_after_it(self) -> None:
        cases = {
            "clojure -M:cljfmt check": CHECKS,
            "clojure -M:cljfmt fix": APPLIES,
            "clojure -M:cljfmt": None,
            "clojure -M:lint check": None,
            "clojure -M:cljfmt --verbose": None,
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(_provided(CLJFMT.claims(command(line), Facts())), expected)


class GithubStatusFunctionTests(unittest.TestCase):
    KNOWN = Known(os="Linux", matrix={}, env={})

    def test_status_functions_without_arguments_are_known(self) -> None:
        cases = {"success()": True, "always()": True, "failure()": False, "cancelled()": False}
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertIs(evaluate(expression, self.KNOWN), expected)

    def test_other_calls_without_their_arguments_are_unknown(self) -> None:
        for expression in ("contains()", "startsWith()", "success('x')", "hashFiles()", "contains('a')"):
            with self.subTest(expression=expression):
                self.assertIsNone(evaluate(expression, self.KNOWN))


class JuliaCompatTests(unittest.TestCase):
    def test_a_package_bounding_every_dependency_is_locked(self) -> None:
        text = 'name = "Pkg1"\n[deps]\nJSON = "uuid"\n[compat]\nJSON = "0.21"\njulia = "1.10"\n'
        self.assertEqual(
            list(_bounded("Project.toml", text)), [Locked(origin=Origin(path="Project.toml"), manager="Pkg")]
        )

    def test_an_unbounded_dependency_a_missing_name_or_no_dependencies_is_not(self) -> None:
        for text in (
            'name = "Pkg1"\n[deps]\nJSON = "uuid"\nHTTP = "uuid"\n[compat]\nJSON = "0.21"\n',
            '[deps]\nJSON = "uuid"\n[compat]\nJSON = "0.21"\n',
            'name = "Pkg1"\n[compat]\njulia = "1.10"\n',
        ):
            with self.subTest(text=text):
                self.assertEqual(list(_bounded("Project.toml", text)), [])


class DotnetSecurityAnalysisTests(unittest.TestCase):
    @staticmethod
    def _setting(key: str, value: str) -> Setting:
        return Setting(origin=Origin(path="Directory.Build.props"), tool="MSBuild", key=key, value=value)

    def test_security_analysis_turned_up_or_the_package_scans(self) -> None:
        for key, value in (
            ("AnalysisModeSecurity", "Recommended"),
            ("AnalysisModeSecurity", "All"),
            ("SecuritySeverity", "error"),
            ("PackageReference", "SecurityCodeScan.VS2019"),
        ):
            with self.subTest(key=key, value=value):
                facts = Facts([self._setting(key, value)])
                self.assertIsNotNone(_security_analysis(command("dotnet build"), facts))

    def test_lookalike_settings_or_no_build_do_not(self) -> None:
        for key, value in (
            ("AnalysisModeSecurity", "None"),
            ("AnalysisModeSecurity", "Default"),
            ("AnalysisMode", "All"),
            ("PackageReference", "Serilog"),
            ("PackageReference", "MySecurityCodeScanFork"),
        ):
            with self.subTest(key=key, value=value):
                facts = Facts([self._setting(key, value)])
                self.assertIsNone(_security_analysis(command("dotnet build"), facts))
        facts = Facts([self._setting("AnalysisModeSecurity", "All")])
        self.assertIsNone(_security_analysis(command("dotnet format"), facts))
        self.assertIsNotNone(_security_analysis(command("dotnet test"), facts))

    def test_a_run_that_does_not_build_runs_no_analyzers(self) -> None:
        facts = Facts([self._setting("AnalysisModeSecurity", "All")])
        for line in ("dotnet test --no-build", "dotnet run --no-build", "dotnet pack --no-build"):
            with self.subTest(line=line):
                self.assertIsNone(_security_analysis(command(line), facts))


if __name__ == "__main__":
    unittest.main()
