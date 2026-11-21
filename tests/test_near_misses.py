"""Recognisers shown what they must reject as well as what they accept: the lookalike programs, fixing runs and
disabling settings that would otherwise credit a project with a practice it does not have (upstream #301)."""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from project_validator.build_systems.cmake import ctest
from project_validator.ci.github_actions import _own
from project_validator.ci.github_expressions import Known, evaluate
from project_validator.core import Options, Project
from project_validator.ecosystems.beam import MIX_FORMAT
from project_validator.ecosystems.clojure import CLJFMT
from project_validator.ecosystems.dotnet.tools import _security_analysis
from project_validator.ecosystems.go import _excluded_everywhere
from project_validator.ecosystems.julia import _bounded
from project_validator.ecosystems.python.hatch import _environments, _script
from project_validator.ecosystems.python.tox import _toml_tables
from project_validator.facts import ConfigurationFile, Facts, Origin, Setting
from project_validator.facts.dependencies import Locked
from project_validator.facts.formatting import FORMAT, Enforcement, _keeps
from project_validator.facts.structure import SourceFile
from project_validator.facts.tools import Run, defined_by
from project_validator.tools.audits import _gitlab_dependency_scanning
from project_validator.tools.scanners import multi_language_scanners
from tests.support import command, temp_project

CHECKS = {FORMAT: frozenset({str(Enforcement.CHECK)})}
APPLIES = {FORMAT: frozenset({str(Enforcement.APPLY)})}


def _provided(run: Run | None) -> Mapping[str, frozenset[str]] | None:
    return None if run is None else run.provides


class ScannerSpellingTests(unittest.TestCase):
    def test_codeql_and_semgrep_scan_by_each_of_their_commands(self) -> None:
        tools = {tool.name: tool for tool in multi_language_scanners(frozenset({"Python"}))}
        cases = {
            ("CodeQL", "codeql database analyze db"): True,
            ("CodeQL", "codeql database create db"): False,
            ("semgrep", "semgrep ci"): True,
            ("semgrep", "semgrep scan --error"): True,
            ("semgrep", "semgrep --config auto"): True,
            ("semgrep", "semgrep login"): False,
        }
        for (name, line), scans in cases.items():
            with self.subTest(line=line):
                self.assertIs(tools[name].claims(command(line), Facts()) is not None, scans)

    def test_each_scanner_reads_only_the_languages_it_knows(self) -> None:
        self.assertEqual(multi_language_scanners(frozenset({"Klingon"})), ())
        found = multi_language_scanners(frozenset({"Python", "Klingon"}))
        self.assertEqual([tool.name for tool in found], ["CodeQL", "GitLab SAST", "semgrep"])
        self.assertTrue(all(tool.languages == frozenset({"Python"}) for tool in found))


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

    def test_string_functions_ignore_case(self) -> None:
        cases = {
            "contains('Hello', 'ELL')": True,
            "contains('Hello', 'x')": False,
            "startsWith('Hello', 'he')": True,
            "startsWith('Hello', 'lo')": False,
            "endsWith('Hello', 'LO')": True,
            "endsWith('Hello', 'he')": False,
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertIs(evaluate(expression, self.KNOWN), expected)

    def test_only_from_json_of_one_known_text_is_parsed(self) -> None:
        cases = {
            "fromJSON('true')": True,
            "fromJSON('false')": False,
            "hashFiles('true')": None,
            "fromJSON('true', 'x')": None,
            "fromJSON(steps.a.outputs.b)": None,
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertIs(evaluate(expression, self.KNOWN), expected)


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


class TomlDocumentShapeTests(unittest.TestCase):
    """A table of the wrong type, or missing, reads as no environments rather than raising or counting."""

    def test_hatch_environments(self) -> None:
        cases = [
            ("hatch.toml", "[envs.test]\nscripts = {}\n", {"test": {"scripts": {}}}),
            ("pyproject.toml", "[tool.hatch.envs.test]\n", {"test": {}}),
            ("pyproject.toml", "[project]\nname = 'x'\n", {}),
            ("pyproject.toml", "tool = 1\n", {}),
            ("pyproject.toml", "[tool]\nhatch = 1\n", {}),
            ("hatch.toml", "envs = 'test'\n", {}),
            ("hatch.toml", "envs = [", {}),
        ]
        for path, text, expected in cases:
            with self.subTest(path=path, text=text):
                self.assertEqual(_environments(path, text), expected)

    def test_tox_tables(self) -> None:
        cases = [
            ("tox.toml", "env_list = ['a']\n", {"env_list": ["a"]}),
            ("pyproject.toml", "[tool.tox]\nenv_list = ['a']\n", {"env_list": ["a"]}),
            ("pyproject.toml", "[project]\nname = 'x'\n", None),
            ("pyproject.toml", "tool = 1\n", None),
            ("pyproject.toml", "[tool]\ntox = 1\n", None),
            ("pyproject.toml", "[tool.tox]\n", None),
            ("tox.toml", "", None),
            ("tox.toml", "env_list = [", None),
        ]
        for path, text, expected in cases:
            with self.subTest(path=path, text=text):
                self.assertEqual(_toml_tables(path, text), expected)


class BuiltTestsProbeTests(unittest.TestCase):
    def test_ctest_runs_only_with_build_options_and_a_cmake_project(self) -> None:
        cases = (({"CMakeLists.txt": "project(x)\n"}, Options(build=True), 1), ({"main.c": ""}, Options(build=True), 0))
        cases += (({"CMakeLists.txt": "project(x)\n"}, None, 0),)
        for files, options, built in cases:
            with self.subTest(files=list(files), options=options), temp_project(files) as root:
                with mock.patch.object(ctest, "count_built_tests", return_value=3) as count:
                    found = list(ctest._built_tests(Project(root), options))
                self.assertEqual(count.call_count, built)
                self.assertEqual(len(found), built)

    def test_the_build_configures_builds_and_lists_in_one_build_tree(self) -> None:
        calls: list[list[str]] = []

        def run(argv: list[str]) -> str:
            calls.append(argv)
            return '{"tests": [{"name": "a"}, {"name": "b"}]}'

        with mock.patch.object(ctest, "_run", side_effect=run):
            count = ctest.count_built_tests(Path("/src"), Options(build=True, cmake="cm", ctest="ct"))
        build = calls[0][4]
        self.assertTrue(Path(build).name.startswith("project_validator_"))
        self.assertEqual(count, 2)
        self.assertEqual(
            calls,
            [
                ["cm", "-S", str(Path("/src")), "-B", build, "-DCMAKE_BUILD_TYPE=Debug"],
                ["cm", "--build", build, "--config", "Debug"],
                ["ct", "--test-dir", build, "-C", "Debug", "--show-only=json-v1"],
            ],
        )


class OwnReusableWorkflowTests(unittest.TestCase):
    def test_only_this_repository_s_workflow_by_its_full_name_is_its_own(self) -> None:
        def load(path: str) -> object:
            return "Apple/Swift-NIO" if path else None

        uses = "apple/swift-nio/.github/workflows/unit.yml@main"
        self.assertEqual(_own(uses, load), ".github/workflows/unit.yml")
        self.assertIsNone(_own("apple/other/.github/workflows/unit.yml@main", load))
        self.assertIsNone(_own("apple/swift-nio@main", load))
        self.assertIsNone(_own(uses, None))
        self.assertIsNone(_own(uses, lambda path: None))


class DefinedByTests(unittest.TestCase):
    def test_a_definition_is_a_file_its_reader_read_or_so_named_or_holding_its_settings(self) -> None:
        facts = Facts(
            [
                ConfigurationFile(origin=Origin(path="a/.clang-format"), reader="clang-format"),
                ConfigurationFile(origin=Origin(path="b/ty.toml"), reader="other"),
                ConfigurationFile(origin=Origin(path="c/x.toml"), reader="other"),
                Setting(origin=Origin(path="pyproject.toml"), tool="ruff", key="line-length", value=120),
            ]
        )
        found = defined_by(files=("clang-format",), named=("ty.toml",), settings=("ruff",))
        self.assertEqual(list(found.found(facts)), ["a/.clang-format", "b/ty.toml", "pyproject.toml"])


class GolangciExclusionTests(unittest.TestCase):
    SOURCES = (
        SourceFile(origin=Origin(path="a/x.go"), language="Go"),
        SourceFile(origin=Origin(path="b/y.go"), language="Go"),
    )

    def excluded(self, rule: object, key: str = "linters.exclusions.rules") -> bool:
        setting = Setting(origin=Origin(path=".golangci.yml"), tool="golangci-lint", key=key, value=(rule,))
        return _excluded_everywhere("errcheck", Facts([*self.SOURCES, setting]))

    def test_a_rule_dropping_the_linter_everywhere_excludes_it(self) -> None:
        self.assertTrue(self.excluded({"linters": ["errcheck"]}))
        self.assertTrue(self.excluded({"linters": ["errcheck"], "path": "."}, key="issues.exclude-rules"))

    def test_a_rule_that_keeps_some_findings_does_not(self) -> None:
        for rule in (
            {"linters": ["errcheck"], "text": "Close"},
            {"linters": ["errcheck"], "path": "^a/"},
            {"linters": ["govet"]},
            {"linters": "errcheck"},
            {"linters": ["errcheck"], "path": "("},
            "errcheck",
        ):
            with self.subTest(rule=rule):
                self.assertFalse(self.excluded(rule))

    def test_only_exclusion_rules_exclude(self) -> None:
        self.assertFalse(self.excluded({"linters": ["errcheck"]}, key="linters.enable"))


class HatchScriptShapeTests(unittest.TestCase):
    def test_a_script_is_a_line_or_a_list_of_lines(self) -> None:
        envs = {
            "test": {"scripts": {"one": "pytest", "many": ["pytest", 1, "coverage report"], "bad": {"x": 1}}},
            "flat": {"scripts": ["pytest"]},
            "bare": "test",
        }
        cases = [
            ("test", "one", ["pytest"]),
            ("test", "many", ["pytest", "coverage report"]),
            ("test", "bad", None),
            ("test", "missing", None),
            ("flat", "one", None),
            ("bare", "one", None),
            ("missing", "one", None),
        ]
        for env, name, expected in cases:
            with self.subTest(env=env, name=name):
                self.assertEqual(_script(envs, env, name), expected)


if __name__ == "__main__":
    unittest.main()
