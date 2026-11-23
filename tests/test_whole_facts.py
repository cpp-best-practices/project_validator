"""Extractors compared on the whole facts they produce, not only on their presence: where each came from (its
origin), its fields, and whether it is heuristic, which messages and --explain rely on (upstream #304)."""

from __future__ import annotations

import json
import unittest

from project_validator.build_systems.make import VARIABLE, _make_targets
from project_validator.ci import CiFile, _heuristic_facts, gitlab, pre_commit_ci
from project_validator.ci.heuristic_providers import TRAVIS_CI
from project_validator.ecosystems import emacs_lisp, ocaml, zig
from project_validator.ecosystems.beam import _bracketed
from project_validator.ecosystems.dotnet.tools import _coverlet, _read_run_settings
from project_validator.ecosystems.haskell.options import ghc_options
from project_validator.ecosystems.javascript import _in_workspaces, _named_config
from project_validator.ecosystems.jvm.analysis import _read_checkstyle
from project_validator.ecosystems.perl import _read_actions
from project_validator.ecosystems.php.tools import _read_phpmd
from project_validator.ecosystems.python.tox import _env_scripts
from project_validator.ecosystems.r import _renv_project
from project_validator.ecosystems.ruby.tools import _read_rake_tasks, _read_simplecov_settings
from project_validator.ecosystems.shell.tools import _read_pester
from project_validator.facts import CiJob, Command, Facts, Origin, Setting, Unknown
from project_validator.facts.analysis import analysed, type_checked
from project_validator.facts.audit import audited
from project_validator.facts.build import Applies, CompilerOption
from project_validator.facts.coverage import Granularity, measured, reported
from project_validator.facts.dependencies import Application
from project_validator.facts.exit_status import POSIX
from project_validator.facts.expansion import Script
from project_validator.facts.fuzzing import fuzzed
from project_validator.facts.limits import limited
from project_validator.facts.links import links_checked
from project_validator.facts.migrations import migrations_linted
from project_validator.facts.mutation import mutated
from project_validator.facts.schema import compatibility_checked, examples_checked, validated
from project_validator.facts.security import scanned
from project_validator.facts.testing import tested
from project_validator.parsing import Span
from project_validator.tools.pre_commit import _read_hooks
from tests.support import command, make_context, temp_project


class HeuristicCiFactTests(unittest.TestCase):
    def test_configuration_that_is_not_parsed_is_a_job_per_os_running_each_line(self) -> None:
        origin = Origin(path=".travis.yml")
        ci_file = CiFile(provider=TRAVIS_CI, path=".travis.yml")

        def job(identity: str, os: str) -> CiJob:
            return CiJob(origin=origin, id=identity, provider="Travis CI", name=".travis.yml", os=os, heuristic=True)

        unknown = Unknown(origin=origin, subject="the jobs and commands", reason="scanned", hides="jobs")
        # One OS: the job is the file. A block scalar's marker (`- |`) runs nothing.
        one = list(_heuristic_facts(ci_file, "script:\n  - |\n  - make test\n", "scanned"))
        make = Command(origin=origin, job=".travis.yml", argv=("make", "test"), line="make test")
        self.assertEqual(one, [job(".travis.yml", "unknown"), make, unknown])
        # Each OS named is a job of its own.
        two = [
            fact
            for fact in _heuristic_facts(ci_file, "os:\n  - linux\n  - osx\n", "scanned")
            if not isinstance(fact, Command)
        ]
        self.assertEqual(two, [job(".travis.yml[linux]", "linux"), job(".travis.yml[macos]", "macos"), unknown])


class GitlabTemplateFactTests(unittest.TestCase):
    def test_a_known_template_is_one_job_running_a_marker_command(self) -> None:
        document = {"include": [{"local": "ci/x.yml"}, {"template": "Security/SAST.gitlab-ci.yml"}]}
        facts = [fact for fact in gitlab.pipeline_facts(".gitlab-ci.yml", document) if not isinstance(fact, Unknown)]
        origin = Origin(path=".gitlab-ci.yml", at=("include", 1))
        identity = ".gitlab-ci.yml:template:Security/SAST.gitlab-ci.yml"
        self.assertEqual(
            facts,
            [
                CiJob(
                    origin=origin,
                    id=identity,
                    provider="GitLab CI",
                    name="Security/SAST.gitlab-ci.yml",
                    os="linux",
                    builds=False,
                ),
                Command(
                    origin=origin,
                    job=identity,
                    argv=("gitlab-template", "Security/SAST.gitlab-ci.yml"),
                    line="template: Security/SAST.gitlab-ci.yml",
                ),
            ],
        )


class GitlabJobFactTests(unittest.TestCase):
    def test_each_job_is_placed_in_the_file_it_comes_from_with_its_runner(self) -> None:
        documents = {"ci/a.yml": {"test": {"tags": ["windows"], "script": ["ctest"]}}}
        document = {
            "include": [{"local": "ci/a.yml"}],
            "default": {"tags": ["macos"]},
            "lint": {"script": ["ruff check"]},
            "bad": {"extends": ".missing"},
        }
        facts = list(gitlab.pipeline_facts(".gitlab-ci.yml", document, documents.get))
        jobs = [(job.origin, job.id, job.provider, job.name, job.os) for job in facts if isinstance(job, CiJob)]
        self.assertEqual(
            jobs,
            [
                (Origin(path="ci/a.yml", at=("test",)), "ci/a.yml:test", "GitLab CI", "test", "windows"),
                (Origin(path=".gitlab-ci.yml", at=("lint",)), ".gitlab-ci.yml:lint", "GitLab CI", "lint", "macos"),
            ],
        )
        commands = [(command.origin, command.job, command.argv) for command in facts if isinstance(command, Command)]
        self.assertEqual(
            commands,
            [
                (Origin(path="ci/a.yml", at=("test", "script", 0)), "ci/a.yml:test", ("ctest",)),
                (Origin(path=".gitlab-ci.yml", at=("lint", "script", 0)), ".gitlab-ci.yml:lint", ("ruff", "check")),
            ],
        )
        unknowns = [
            (unknown.origin, unknown.subject, unknown.hides) for unknown in facts if isinstance(unknown, Unknown)
        ]
        self.assertEqual(unknowns, [(Origin(path=".gitlab-ci.yml", at=("bad",)), "job bad", "commands")])


TOX = """\
[tox]
env_list = py312-lint, py312-test
[testenv:py312-lint]
commands = ruff check {posargs}
[testenv:py312-test]
commands = pytest
"""


class ToxFactTests(unittest.TestCase):
    def test_each_command_is_placed_in_its_section_and_runs_where_tox_ini_is(self) -> None:
        origin = Origin(path="sub/tox.ini", at=("testenv:py312-lint", "commands"))
        expected = [Script(text="ruff check .", origin=origin, directory="sub")]
        for factors in (["lint"], ["py312", "lint"]):
            with self.subTest(factors=factors):
                self.assertEqual(list(_env_scripts("sub/tox.ini", TOX, None, factors)), expected)

    def test_a_tox_ini_that_does_not_parse_is_unknown_at_that_file(self) -> None:
        self.assertEqual(
            list(_env_scripts("sub/tox.ini", "[tox\n", None, [])),
            [
                Unknown(
                    origin=Origin(path="sub/tox.ini"),
                    subject="the tox environments",
                    reason="sub/tox.ini does not parse",
                )
            ],
        )


class PreCommitHookFactTests(unittest.TestCase):
    def test_each_hook_is_placed_at_its_repository_and_index(self) -> None:
        text = (
            "repos:\n- repo: https://x/ruff\n  hooks:\n  - id: ruff\n    args: [--fix]\n  - id: fmt\n    entry: black\n"
        )
        settings = [fact for fact in _read_hooks("p.yaml", text) if isinstance(fact, Setting)]
        hooks = [(setting.origin, setting.tool, setting.key, setting.value) for setting in settings]
        self.assertEqual(
            hooks,
            [
                (
                    Origin(path="p.yaml", at=("repos", 0, "hooks", 0)),
                    "pre-commit",
                    "hook",
                    "https://x/ruff ruff  --fix",
                ),
                (Origin(path="p.yaml", at=("repos", 0, "hooks", 1)), "pre-commit", "hook", "https://x/ruff fmt black"),
            ],
        )

    def test_a_configuration_that_does_not_parse_hides_its_settings(self) -> None:
        [unknown] = [fact for fact in _read_hooks("p.yaml", "repos: [\n") if isinstance(fact, Unknown)]
        self.assertEqual(
            (unknown.origin, unknown.subject, unknown.hides),
            (Origin(path="p.yaml"), "the pre-commit hooks", "settings"),
        )
        self.assertIn("expected the node content", unknown.reason)


class PreCommitCiFactTests(unittest.TestCase):
    def test_pre_commit_ci_is_one_job_running_every_hook_skipping_those_it_skips(self) -> None:
        origin = Origin(path=".pre-commit-config.yaml", at=("ci",))
        job = CiJob(
            origin=origin, id="pre-commit.ci", provider="pre-commit.ci", name="pre-commit.ci", os="linux", builds=False
        )
        line = "pre-commit run --all-files"
        argv = ("pre-commit", "run", "--all-files")
        for document, env in (
            ({"ci": {"skip": ["mypy", "pylint"]}}, {"SKIP": "mypy,pylint"}),
            ({"ci": {"autofix_prs": False}}, {}),
            ({"ci": {"skip": "mypy"}}, {}),
            ({"repos": []}, {}),
            ([], {}),
        ):
            with self.subTest(document=document):
                self.assertEqual(
                    list(pre_commit_ci._facts(".pre-commit-config.yaml", document, lambda _path: None)),
                    [job, Command(origin=origin, job="pre-commit.ci", argv=argv, line=line, env=env)],
                )


class HeuristicSettingsTests(unittest.TestCase):
    """Readers that match settings in code they do not parse mark every setting heuristic, at the file read."""

    CASES = (
        (ocaml._read_tests, "test/dune", "(test (name t1))\n", ("dune tests", "test", "t1")),
        (
            ocaml._read_flags,
            "src/dune",
            "(library (name x) (flags (:standard -w +a)))\n",
            ("dune", "flags", "(:standard -w +a)"),
        ),
        (
            emacs_lisp._read_eask_commands,
            "Eask",
            "(eask-defcommand test\n  (ert-run-tests-batch-and-exit))\n",
            ("Eask commands", "test", True),
        ),
        (
            _read_pester,
            "tests/run.ps1",
            "$config.CodeCoverage.Enabled = $true\n",
            ("Pester", "CodeCoverage.Enabled", True),
        ),
        (_read_rake_tasks, "Rakefile", "Rake::TestTask.new(:test)\n", ("Rake", "task.tests", "test")),
        (_read_simplecov_settings, "spec/spec_helper.rb", "SimpleCov.start\n", ("SimpleCov", "start", True)),
        (
            _read_actions,
            "inc/MyBuilder.pm",
            "sub ACTION_authortest {\n    my ($self) = @_;\n    $self->depends_on('test');\n}\n",
            ("Module::Build actions", "authortest", True),
        ),
    )

    def test_each_reader_marks_its_settings_heuristic_at_the_file_it_read(self) -> None:
        for read, path, text, expected in self.CASES:
            with self.subTest(read=read.__qualname__):
                found = list(read(path, text))
                self.assertTrue(found, "nothing read")
                for setting in found:
                    self.assertIsInstance(setting, Setting)
                    self.assertEqual((setting.origin.path, setting.heuristic), (path, True))
                if expected is not None:
                    self.assertIn(expected, [(setting.tool, setting.key, setting.value) for setting in found])

    def test_an_executable_in_build_zig_is_read_at_that_file(self) -> None:
        text = 'const exe = b.addExecutable(.{ .name = "app", .root_source_file = b.path("src/main.zig") });\n'
        self.assertEqual(
            list(zig._read_programs("build.zig", text)),
            [Setting(origin=Origin(path="build.zig"), tool=zig.PROGRAMS, key="executable", value=True)],
        )


PROVIDES = {
    tested: ("test", "runs"),
    analysed: ("analysis", "checks"),
    scanned: ("security", "scans"),
    audited: ("audit", "runs"),
    fuzzed: ("fuzz", "runs"),
    links_checked: ("links", "checked"),
    migrations_linted: ("migrations", "linted"),
    mutated: ("mutation", "runs"),
    validated: ("schema", "validates"),
    examples_checked: ("examples", "checked"),
    compatibility_checked: ("compatibility", "breaking"),
}


class RunHelperTests(unittest.TestCase):
    """The helpers that build a run keep the reads and heuristic flag they are given."""

    def test_heuristic_and_read_pass_through(self) -> None:
        read = ("Rakefile",)
        for heuristic in (True, False):
            for run in (
                tested(read=read, heuristic=heuristic),
                analysed(read=read, heuristic=heuristic),
                scanned(read=read, heuristic=heuristic),
                measured(Granularity.LINE, read=read, heuristic=heuristic),
                reported(Granularity.LINE, read=read, heuristic=heuristic),
            ):
                with self.subTest(run=run):
                    self.assertEqual((run.heuristic, run.read), (heuristic, read))

    def test_every_helper_s_run_is_not_heuristic_and_reads_nothing_by_default(self) -> None:
        for helper in PROVIDES:
            with self.subTest(helper=helper.__name__):
                run = helper()
                self.assertEqual((run.heuristic, tuple(run.read)), (False, ()))
        for helper, (aspect, level) in PROVIDES.items():
            with self.subTest(helper=helper.__name__):
                self.assertEqual(dict(helper().provides), {aspect: frozenset({level})})
        for run in (type_checked(strict=True), limited(), measured(Granularity.LINE), reported(Granularity.LINE)):
            with self.subTest(run=run):
                self.assertEqual((run.heuristic, tuple(run.read)), (False, ()))


class SmallExtractorTests(unittest.TestCase):
    def test_a_phpmd_rule_set_s_rules_and_exclusions(self) -> None:
        text = (
            '<ruleset><rule ref="rulesets/codesize.xml"><exclude name="TooManyMethods"/><exclude/></rule>'
            "<rule/></ruleset>"
        )
        self.assertEqual(
            list(_read_phpmd("phpmd.xml", text)),
            [
                Setting(
                    origin=Origin(path="phpmd.xml", at=("rules",)),
                    tool="PHPMD",
                    key="rules",
                    value=("rulesets/codesize.xml", ""),
                ),
                Setting(
                    origin=Origin(path="phpmd.xml", at=("excluded",)),
                    tool="PHPMD",
                    key="excluded",
                    value=("TooManyMethods", ""),
                ),
            ],
        )

    def test_each_workspace_package_s_script_is_placed_in_its_package_json(self) -> None:
        files = {
            "package.json": json.dumps({"workspaces": ["packages/*"]}),
            "packages/a/package.json": json.dumps({"scripts": {"test": "vitest a"}}),
            "packages/b/package.json": "{}",
        }
        with temp_project(files) as root:
            found = _in_workspaces(command("turbo run test"), make_context(root), "test")
        path = "packages/a/package.json"
        self.assertEqual(
            found,
            [
                Script(
                    text="vitest a",
                    origin=Origin(path=path, at=("scripts", "test")),
                    directory="packages/a",
                    shell=POSIX,
                )
            ],
        )


class CoverletRunTests(unittest.TestCase):
    def test_each_way_coverlet_runs_says_what_it_measures_and_reads(self) -> None:
        both = (Granularity.LINE, Granularity.BRANCH)
        self.assertEqual(_coverlet(command("coverlet bin/x.dll"), Facts()), reported(*both))
        collect = command('dotnet test --collect:"XPlat Code Coverage"')
        self.assertEqual(_coverlet(collect, Facts()), measured(*both))
        self.assertEqual(_coverlet(command("dotnet test /p:CollectCoverage=true"), Facts()), reported(*both))
        # Settings: MSBuild's CollectCoverage, and a .runsettings that MSBuild names, which adds the collector.
        project = Origin(path="tests/Directory.Build.props")
        collects = Setting(origin=project, tool="MSBuild", key="CollectCoverage", value="True")
        names = Setting(origin=project, tool="MSBuild", key="RunSettingsFilePath", value=".\\ci\\a.runsettings")
        collector = Setting(
            origin=Origin(path="tests/ci/a.runsettings"),
            tool="VSTest",
            key="DataCollector",
            value="XPlat Code Coverage",
        )
        unrelated = Setting(origin=project, tool="Other", key="CollectCoverage", value="true")
        facts = Facts([collects, names, collector, unrelated])
        self.assertEqual(_coverlet(command("dotnet test"), facts), measured(*both, read=[collects, collector]))
        self.assertIsNone(_coverlet(command("dotnet test"), Facts([unrelated])))
        self.assertIsNone(_coverlet(command("dotnet build"), facts))


class XmlAndProfileReaderTests(unittest.TestCase):
    def test_a_runsettings_file_s_data_collectors_by_friendly_name(self) -> None:
        text = (
            "<RunSettings><DataCollectionRunSettings><DataCollectors>"
            '<DataCollector friendlyName="XPlat Code Coverage"/><DataCollector/>'
            "</DataCollectors></DataCollectionRunSettings></RunSettings>"
        )
        origin = Origin(path="a.runsettings", at=("DataCollector",))
        self.assertEqual(
            list(_read_run_settings("a.runsettings", text)),
            [
                Setting(origin=origin, tool="VSTest", key="DataCollector", value="XPlat Code Coverage"),
                Setting(origin=origin, tool="VSTest", key="DataCollector", value=""),
            ],
        )
        # A file that does not parse is matched heuristically.
        broken = '<RunSettings><DataCollector friendlyName="XPlat Code Coverage">'
        self.assertEqual(
            list(_read_run_settings("a.runsettings", broken)),
            [Setting(origin=origin, tool="VSTest", key="DataCollector", value="XPlat Code Coverage", heuristic=True)],
        )

    def test_a_checkstyle_configuration_s_modules(self) -> None:
        self.assertEqual(
            list(_read_checkstyle("c.xml", '<module name="Checker"><module/></module>')),
            [
                Setting(
                    origin=Origin(path="c.xml", at=("modules",)),
                    tool="Checkstyle",
                    key="modules",
                    value=("Checker", ""),
                )
            ],
        )
        self.assertEqual(
            list(_read_checkstyle("c.xml", "<module")),
            [
                Unknown(
                    origin=Origin(path="c.xml"),
                    subject="the Checkstyle settings",
                    reason="unclosed token: line 1, column 0",
                    hides="settings",
                    tools=("Checkstyle",),
                )
            ],
        )

    def test_an_rprofile_activating_renv_makes_an_application(self) -> None:
        self.assertEqual(
            list(_renv_project(".Rprofile", 'source("renv/activate.R")\n')),
            [Application(origin=Origin(path=".Rprofile"), manager="R packages")],
        )
        self.assertEqual(list(_renv_project(".Rprofile", "options(repos = 'x')\n")), [])


class MoreReaderTests(unittest.TestCase):
    def test_each_rake_test_task_by_its_name_or_its_kind_s_default(self) -> None:
        text = (
            "RSpec::Core::RakeTask.new\nRake::TestTask.new(:unit)\n"
            "Minitest::TestTask.create\nRSpec::Core::RakeTask.new :fast\n"
        )
        origin = Origin(path="Rakefile", at=("task", "tests"))
        self.assertEqual(
            list(_read_rake_tasks("Rakefile", text)),
            [
                Setting(origin=origin, tool="Rake", key="task.tests", value=name, heuristic=True)
                for name in ("spec", "unit", "test", "fast")
            ],
        )

    def test_ghc_options_hold_for_ghc_and_haskell_where_their_conditions_do(self) -> None:
        found = list(
            ghc_options("x.cabal", "Cabal", "library", ("-Wall",), frozenset({"flag(dev)", "not impl(ghc < 9)"}))
        )
        applies = Applies(
            compilers=frozenset({"ghc"}),
            languages=frozenset({"Haskell"}),
            requires=frozenset({"flag(dev)", "NOT impl(ghc < 9)"}),
        )
        self.assertEqual(
            found,
            [
                CompilerOption(
                    origin=Origin(path="x.cabal"),
                    build_system="Cabal",
                    option="-Wall",
                    applies=applies,
                    target="library",
                )
            ],
        )

    def test_a_runner_s_named_configuration_relative_to_where_it_runs(self) -> None:
        named = _named_config("vitest")
        in_web = Command(origin=Origin(path="ci.yml"), job="j", argv=("vitest", "-c", "v.ts"), line="", directory="web")
        self.assertEqual(named(in_web), ["web/v.ts"])
        self.assertEqual(named(command("vitest --config a.ts")), ["a.ts"])
        self.assertEqual(named(command("jest --config a.ts")), [])
        self.assertEqual(named(command("vitest run")), [])

    def test_a_bracketed_list_with_its_nested_lists(self) -> None:
        self.assertEqual(_bracketed("x [a, [b], c] y", 2), "[a, [b], c]")
        self.assertEqual(_bracketed("[a, [b", 0), "[a, [b")
        self.assertEqual(_bracketed("a]b[c]", 3), "[c]")


def _make(files: dict[str, str], line: str) -> list[object]:
    with temp_project(files) as root:
        found = _make_targets(command(line), make_context(root))
        return [] if found is None else list(found)


class MakeExpansionTests(unittest.TestCase):
    CI = Origin(path="ci.yml")

    def test_make_where_cmake_configured_in_place_builds_its_targets(self) -> None:
        lists = "build/CMakeLists.txt"
        self.assertEqual(
            _make({lists: "project(x)\n"}, "make -C build test lint"),
            [
                Script(text="cmake --build build --target test", origin=Origin(path=lists, at=("test",))),
                Script(text="cmake --build build --target lint", origin=Origin(path=lists, at=("lint",))),
            ],
        )
        self.assertEqual(
            _make({"CMakeLists.txt": "project(x)\n"}, "make"),
            [Script(text="cmake --build . --target all", origin=Origin(path="CMakeLists.txt", at=("all",)))],
        )

    def test_make_without_a_makefile_or_a_rule_is_unknown(self) -> None:
        self.assertEqual(
            _make({"a.c": ""}, "make"),
            [Unknown(origin=self.CI, subject="the makefile", reason="none is found where make runs", hides="commands")],
        )
        reason = "no rule of the makefile (or of the makefiles it includes) builds it"
        self.assertEqual(
            _make({"Makefile": "all:\n\techo\n"}, "make missing other"),
            [
                Unknown(origin=self.CI, subject=f"the make target {goal}", reason=reason, hides="commands")
                for goal in ("missing", "other")
            ],
        )

    def test_each_recipe_is_placed_at_its_rule_and_line(self) -> None:
        makefile = "t:\n\t$(TOOL) x\n\t@-+${OTHER} y\n%.o: %.c\n\tcc -c $*.c -o $@\n%.c:\n\tgen $@\n"
        unset = "which neither the makefile nor the command line sets"

        def at(target: str, line: int, end: int) -> Origin:
            return Origin(path="Makefile", at=(target,), span=Span(line, 1, line, end))

        def unknown(origin: Origin, recipe: str, name: str) -> Unknown:
            reason = f"its program is the variable {name}, {unset}"
            return Unknown(origin=origin, subject=f"the recipe {recipe!r}", reason=reason, hides="commands")

        self.assertEqual(
            _make({"Makefile": makefile}, "make t a.o"),
            [
                unknown(at("t", 2, 11), "$(TOOL) x", "TOOL"),
                unknown(at("t", 3, 15), "${OTHER} y", "OTHER"),
                Script(text="gen a.c", origin=at("a.c", 7, 8), opaque=VARIABLE, shell=POSIX),
                Script(text="cc -c a.c -o a.o", origin=at("a.o", 5, 18), opaque=VARIABLE, shell=POSIX),
            ],
        )


if __name__ == "__main__":
    unittest.main()
