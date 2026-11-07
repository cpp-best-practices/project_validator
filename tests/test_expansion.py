"""Command expansion: the commands CI's commands run in turn, through Make targets and pre-commit hooks."""

import unittest

from project_validator.build_systems.make import parse_makefile
from project_validator.facts import Command, Facts, Origin, Unknown
from project_validator.facts.arguments import positional
from project_validator.facts.expansion import CommandExpander, built_in_expanders
from tests.support import GITHUB_WORKFLOW, github_job, make_context, temp_project


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _expanded(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command) if command.via]


class EngineTests(unittest.TestCase):
    def test_expanders_are_found_in_profiles_and_shared_modules(self) -> None:
        names = {expander.name for expander in built_in_expanders()}
        self.assertLessEqual({"Make targets", "pre-commit hooks", "package.json scripts", "Composer scripts"}, names)
        self.assertTrue(all(isinstance(expander, CommandExpander) for expander in built_in_expanders()))

    def test_an_expanded_command_records_the_chain_that_ran_it(self) -> None:
        files = {
            "Makefile": "check: lint\n\tctest\nlint:\n\t$(MAKE) format\nformat:\n"
            "\tclang-format --dry-run -Werror a.cpp\n",
            **github_job("ubuntu-latest", "make check"),
        }
        commands = {command.argv: command for command in _facts(files).of(Command)}
        formatting = commands[("clang-format", "--dry-run", "-Werror", "a.cpp")]
        self.assertEqual(
            [str(origin) for origin in formatting.via],
            [f"{GITHUB_WORKFLOW}:jobs.build.steps[0].run", "Makefile:lint[4]"],
        )
        self.assertEqual(str(formatting.origin), "Makefile:format[6]")
        self.assertEqual(formatting.job, f"{GITHUB_WORKFLOW}:build")

    def test_launchers_and_wrappers_run_the_command_that_follows(self) -> None:
        files = github_job(
            "ubuntu-latest", "sudo -u ci env CC=clang CXX=clang++ emcmake cmake -S .", "npx --yes", "nice -n 5"
        )
        launched = {command.argv: command.env for command in _facts(files).of(Command) if command.via}
        self.assertEqual(
            list(launched),
            [
                ("env", "CC=clang", "CXX=clang++", "emcmake", "cmake", "-S", "."),
                ("emcmake", "cmake", "-S", "."),
                ("cmake", "-S", "."),
            ],
        )
        self.assertEqual(launched[("cmake", "-S", ".")], {"CC": "clang", "CXX": "clang++"})

    def test_cd_changes_where_the_rest_of_the_script_runs(self) -> None:
        files = {
            "web/ui/package.json": '{"scripts": {"lint": "eslint ."}}',
            **github_job("ubuntu-latest", "cd web/ui && npm run lint\ncd ../.. && pwd\ncd $GITHUB_WORKSPACE/web && ls"),
        }
        commands = [(command.argv, command.directory) for command in _facts(files).of(Command)]
        self.assertIn((("eslint", "."), "web/ui"), commands)
        self.assertIn((("pwd",), "."), commands)
        self.assertIn((("ls",), "web"), commands)

    def test_what_runs_outside_the_project_is_not_expanded(self) -> None:
        for script in (
            "cd /tmp/other && make",
            "cd $HOME && make",
            "cd ../sibling && make",
            "cd build && make",
            "make -C build",
        ):
            with self.subTest(script=script):
                found = _facts({"Makefile": "all:\n\techo hi\n", **github_job("ubuntu-latest", script)})
                self.assertEqual((_expanded(found), found.of(Unknown)), ([], ()))

    def test_a_definition_that_runs_itself_is_followed_once(self) -> None:
        files = {"Makefile": "all:\n\t$(MAKE) all\n\techo done\n", **github_job("ubuntu-latest", "make")}
        self.assertEqual(_expanded(_facts(files)), [("make", "all"), ("echo", "done")])

    def test_positional_arguments_and_option_values(self) -> None:
        self.assertEqual(
            positional(
                ("npm", "--prefix", "web", "run", "--silent", "lint", "--dir=x"), frozenset({"--prefix", "--dir"})
            ),
            (["run", "lint"], {"--prefix": "web", "--dir": "x"}),
        )


class MakeTests(unittest.TestCase):
    MAKEFILE = """\
CC := gcc
.PHONY: all check
all: build

build: src/a.c
\t@$(CC) -o app src/a.c
check: build ; ./app --selftest
\t-$(MAKE) -C docs lint
lint:
\tclang-format --dry-run -Werror \\
\t  src/a.c
"""

    def test_rules_their_prerequisites_and_the_default_goal(self) -> None:
        makefile = parse_makefile(self.MAKEFILE)
        self.assertEqual(makefile.default, "all")
        self.assertEqual(list(makefile.rules), [".PHONY", "all", "build", "check", "lint"])
        self.assertEqual(makefile.rules["check"].recipe, [(7, "./app --selftest"), (8, "make -C docs lint")])
        self.assertEqual(makefile.rules["lint"].recipe[0][0], 10)

    def test_make_runs_the_named_targets_after_their_prerequisites(self) -> None:
        files = {"Makefile": self.MAKEFILE, **github_job("ubuntu-latest", "make check")}
        self.assertEqual(
            _expanded(_facts(files)),
            [("$(CC)", "-o", "app", "src/a.c"), ("./app", "--selftest"), ("make", "-C", "docs", "lint")],
        )

    def test_without_a_target_make_runs_the_default_goal(self) -> None:
        files = {"Makefile": self.MAKEFILE, **github_job("ubuntu-latest", "make -j4 CC=clang")}
        self.assertEqual(_expanded(_facts(files)), [("$(CC)", "-o", "app", "src/a.c")])

    def test_the_makefile_is_found_where_make_runs(self) -> None:
        files = {"docs/GNUmakefile": "lint:\n\tvale .\n", **github_job("ubuntu-latest", "make -C docs lint")}
        self.assertEqual(_expanded(_facts(files)), [("vale", ".")])
        named = {"build.mk": "test:\n\tctest\n", **github_job("ubuntu-latest", "make -f build.mk test")}
        self.assertEqual(_expanded(_facts(named)), [("ctest",)])

    def test_a_missing_makefile_is_unknown(self) -> None:
        facts = _facts(github_job("ubuntu-latest", "make check"))
        self.assertEqual(
            [(fact.subject, fact.reason) for fact in facts.of(Unknown)],
            [("the makefile", "none is found where make runs")],
        )


class PreCommitTests(unittest.TestCase):
    CONFIG = """\
        repos:
          - repo: https://github.com/astral-sh/ruff-pre-commit
            rev: v0.14.0
            hooks:
              - id: ruff
                args: [--fix]
              - id: ruff-format
          - repo: local
            hooks:
              - id: mypy
                name: mypy
                entry: mypy --strict
                language: system
                args: [src]
              - id: manual-only
                entry: lizard -L 30
                language: system
                stages: [manual]
        """

    def test_pre_commit_run_runs_each_hook(self) -> None:
        files = {".pre-commit-config.yaml": self.CONFIG, **github_job("ubuntu-latest", "pre-commit run --all-files")}
        facts = _facts(files)
        self.assertEqual(_expanded(facts), [("ruff", "--fix"), ("ruff-format",), ("mypy", "--strict", "src")])
        ruff = next(command for command in facts.of(Command) if command.argv[0] == "ruff")
        self.assertEqual(
            (ruff.line, ruff.origin),
            (
                "the ruff hook of https://github.com/astral-sh/ruff-pre-commit",
                Origin(path=".pre-commit-config.yaml", at=("repos", 0, "hooks", 0)),
            ),
        )

    def test_a_named_hook_or_stage_runs_only_those_hooks(self) -> None:
        for command, expected in (
            ("pre-commit run mypy --all-files", [("mypy", "--strict", "src")]),
            (
                "prek run --hook-stage manual",
                [("ruff", "--fix"), ("ruff-format",), ("mypy", "--strict", "src"), ("lizard", "-L", "30")],
            ),
        ):
            with self.subTest(command=command):
                files = {".pre-commit-config.yaml": self.CONFIG, **github_job("ubuntu-latest", command)}
                self.assertEqual(_expanded(_facts(files)), expected)

    def test_a_missing_or_broken_configuration_is_unknown(self) -> None:
        for files, reason in (
            ({}, "no pre-commit configuration is found"),
            ({".pre-commit-config.yaml": "repos: [\n"}, ".pre-commit-config.yaml does not parse"),
        ):
            with self.subTest(reason=reason):
                facts = _facts({**files, **github_job("ubuntu-latest", "pre-commit run -a")})
                self.assertTrue(facts.of(Unknown)[0].reason.startswith(reason))

    def test_malformed_hooks_are_skipped(self) -> None:
        config = "repos:\n  - text\n  - repo: local\n    hooks: [text, {name: no id}, {id: ok, entry: echo ok}]\n"
        files = {".pre-commit-config.yaml": config, **github_job("ubuntu-latest", "pre-commit run")}
        self.assertEqual(_expanded(_facts(files)), [("echo", "ok")])

    def test_other_pre_commit_commands_run_no_hooks(self) -> None:
        files = {".pre-commit-config.yaml": self.CONFIG, **github_job("ubuntu-latest", "pre-commit install")}
        self.assertEqual(_expanded(_facts(files)), [])
