"""Command expansion: the commands CI's commands run in turn, through Make targets and pre-commit hooks."""

from __future__ import annotations

import json
import unittest
from typing import ClassVar

from project_validator.build_systems.make import parse_makefile
from project_validator.ecosystems.python.tox import braces
from project_validator.facts import Command, Facts, Origin, Unknown, as_dict, resolved
from project_validator.facts.arguments import positional
from project_validator.facts.expansion import CommandExpander, known_expanders
from project_validator.facts.tools import ToolRun
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, temp_project


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _expanded(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command) if command.via]


class EngineTests(unittest.TestCase):
    def test_expanders_are_found_in_profiles_and_shared_modules(self) -> None:
        names = {expander.name for expander in known_expanders()}
        self.assertLessEqual({"Make targets", "pre-commit hooks", "package.json scripts", "Composer scripts"}, names)
        self.assertTrue(all(isinstance(expander, CommandExpander) for expander in known_expanders()))

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

    def test_xargs_runs_its_command_with_the_arguments_it_reads(self) -> None:
        files = github_job("ubuntu-latest", "git ls-files '*.cpp' | xargs -n 1 -P4 clang-format --dry-run -Werror")
        launched = [command.argv for command in _facts(files).of(Command) if command.via]
        self.assertEqual(launched, [("clang-format", "--dry-run", "-Werror")])

    def test_timeout_runs_the_command_after_its_duration(self) -> None:
        files = github_job(
            "ubuntu-latest",
            "timeout 5m mutmut run",
            "timeout --signal=INT --kill-after=2m 30m mutmut run 'pkg.x_f*'",
            "timeout -s INT -k 2m -v 30m make check",
            "timeout 30m",
        )
        launched = [command.argv for command in _facts(files).of(Command) if command.via]
        self.assertEqual(launched, [("mutmut", "run"), ("mutmut", "run", "pkg.x_f*"), ("make", "check")])

    def test_cd_changes_where_the_rest_of_the_script_runs(self) -> None:
        files = {
            "web/ui/package.json": '{"scripts": {"lint": "eslint ."}}',
            **github_job("ubuntu-latest", "cd web/ui && npm run lint\ncd ../.. && pwd\ncd $GITHUB_WORKSPACE/web && ls"),
        }
        commands = [(command.argv, command.directory) for command in _facts(files).of(Command)]
        self.assertIn((("eslint", "."), "web/ui"), commands)
        self.assertIn((("pwd",), "."), commands)
        self.assertIn((("ls",), "web"), commands)

    def test_a_directory_a_variable_names_is_unknown_not_elsewhere(self) -> None:
        files = {"CMakeLists.txt": "enable_testing()\n", **github_job("x", "cd $BUILD_DIR && ctest && make")}
        with temp_project(files) as root:
            facts = make_context(root).facts
        commands = {command.argv[0]: command.directory for command in facts.of(Command)}
        # Nothing is expanded there (its makefile cannot be read), but a tool run there covers the whole project.
        self.assertEqual(commands, {"cd": "$BUILD_DIR", "ctest": "$BUILD_DIR", "make": "$BUILD_DIR"})
        [run] = facts.of(ToolRun)
        self.assertEqual((run.tool, run.scope, run.heuristic), ("ctest", (".",), True))

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
        self.assertEqual(makefile.rules["check"].recipe, [(7, "./app --selftest"), (8, "-make -C docs lint")])
        self.assertEqual(makefile.rules["lint"].recipe[0][0], 10)

    def test_make_runs_the_named_targets_after_their_prerequisites(self) -> None:
        files = {"Makefile": self.MAKEFILE, **github_job("ubuntu-latest", "make check")}
        self.assertEqual(
            _expanded(_facts(files)),
            [("gcc", "-o", "app", "src/a.c"), ("./app", "--selftest"), ("make", "-C", "docs", "lint")],
        )

    def test_without_a_target_make_runs_the_default_goal(self) -> None:
        files = {"Makefile": self.MAKEFILE, **github_job("ubuntu-latest", "make -j4 CC=clang")}
        self.assertEqual(_expanded(_facts(files)), [("clang", "-o", "app", "src/a.c")])

    def test_the_makefile_is_found_where_make_runs(self) -> None:
        files = {"docs/GNUmakefile": "lint:\n\tvale .\n", **github_job("ubuntu-latest", "make -C docs lint")}
        self.assertEqual(_expanded(_facts(files)), [("vale", ".")])
        named = {"build.mk": "test:\n\tctest\n", **github_job("ubuntu-latest", "make -f build.mk test")}
        self.assertEqual(_expanded(_facts(named)), [("ctest",)])

    def test_comments_and_blank_lines_keep_a_recipe_open_and_other_lines_close_it(self) -> None:
        makefile = parse_makefile("a:\n\techo 1\n# note\n\n\techo 2\nvpath %.c src\n\techo 3\n")
        self.assertEqual(makefile.rules["a"].recipe, [(2, "echo 1"), (5, "echo 2")])

    def test_assignments_append_default_and_drop_comments(self) -> None:
        makefile = parse_makefile("A = x\nA += y\nB ?= 1\nB ?= 2\nC += z\nD = a b # note # more\nE := e\n")
        variables = makefile.variables
        self.assertEqual(
            (variables["A"], variables["B"], variables["C"], variables["D"], variables["E"]),
            ("x y", "1", "z", "a b", "e"),
        )

    def test_includes_and_prerequisites_accumulate(self) -> None:
        makefile = parse_makefile("include a.mk\ninclude b.mk c.mk\nx: a\nx: b c\n")
        self.assertEqual(makefile.includes, ["a.mk", "b.mk", "c.mk"])
        self.assertEqual(makefile.rules["x"].prerequisites, ["a", "b", "c"])

    def test_continued_lines_are_numbered_by_their_first_line(self) -> None:
        makefile = parse_makefile("a: \\\n  b \\\n  c\n\techo \\\n\t  done\n")
        self.assertEqual(makefile.rules["a"].prerequisites, ["b", "c"])
        self.assertEqual([number for number, _ in makefile.rules["a"].recipe], [4])

    def test_recipe_prefixes_are_not_part_of_the_command(self) -> None:
        files = {"Makefile": "all:\n\t@echo a\n\t-echo b\n\t+echo c\n\t@-echo d\n", **github_job("x", "make")}
        self.assertEqual(_expanded(_facts(files)), [("echo", "a"), ("echo", "b"), ("echo", "c"), ("echo", "d")])

    def test_a_doubled_dollar_is_a_dollar_the_shell_sees(self) -> None:
        """Documenter's `$$(biome_jll.biome())` reaches Julia as `$(…)` (#267); `$$(CC)` is no reference to CC."""
        makefile = "CC = gcc\nall:\n\techo $$HOME $$(CC) $(CC)\n"
        files = {"Makefile": makefile, **github_job("x", "make")}
        self.assertEqual(_expanded(_facts(files)), [("echo", "$HOME", "$(CC)", "gcc")])

    def test_a_conditional_the_makefile_decides_takes_its_branch(self) -> None:
        makefile = "V = 1\nall:\nifeq ($(V),1)\n\techo verbose\nelse\n\t@echo quiet\nendif\n"
        files = {"Makefile": makefile, **github_job("x", "make")}
        self.assertEqual(_expanded(_facts(files)), [("echo", "verbose")])

    def test_the_command_line_decides_a_conditional(self) -> None:
        makefile = "all:\nifdef DEBUG\n\tcc -g a.c\nelse\n\tcc -O2 a.c\nendif\n"
        files = {"Makefile": makefile, **github_job("x", "make DEBUG=1")}
        self.assertEqual(_expanded(_facts(files)), [("cc", "-g", "a.c")])

    def test_a_conditional_on_the_environment_reads_every_branch(self) -> None:
        """Where the makefile cannot say (the OS make runs on, a variable only the environment may set), every branch
        is read, as when conditionals were not followed: what CI may run is not narrowed by a guess."""
        makefile = "all:\nifeq ($(OS),Windows_NT)\n\tbuild.bat\nelse\n\t./build.sh\nendif\n"
        files = {"Makefile": makefile, **github_job("x", "make")}
        self.assertEqual(_expanded(_facts(files)), [("build.bat",), ("./build.sh",)])

    def test_what_the_environment_may_override_decides_no_conditional(self) -> None:
        """make's own defaults (CC is cc) and `?=` give way to the environment, which CI often sets (CC=clang): a
        conditional on them reads every branch, as does one on a variable appended to before it is set."""
        for makefile in (
            "all:\nifeq ($(CC),clang)\n\tclang-tidy a.c\nelse\n\tcppcheck a.c\nendif\n",
            "CC ?= gcc\nall:\nifeq ($(CC),clang)\n\tclang-tidy a.c\nelse\n\tcppcheck a.c\nendif\n",
            "CC += -m64\nall:\nifeq ($(CC),clang -m64)\n\tclang-tidy a.c\nelse\n\tcppcheck a.c\nendif\n",
        ):
            with self.subTest(makefile=makefile.splitlines()[0]):
                files = {"Makefile": makefile, **github_job("x", "make")}
                self.assertEqual(_expanded(_facts(files)), [("clang-tidy", "a.c"), ("cppcheck", "a.c")])

    def test_a_branch_not_taken_defines_nothing(self) -> None:
        makefile = parse_makefile("CC = gcc\nifeq ($(CC),clang)\nFLAGS = -Weverything\nfirst:\nendif\nall:\n")
        self.assertNotIn("FLAGS", makefile.variables)
        self.assertEqual((makefile.default, list(makefile.rules)), ("all", ["all"]))

    def test_a_define_body_is_no_rule(self) -> None:
        makefile = parse_makefile("define HELP\nusage: make all\nendef\nall:\n\techo ok\n")
        self.assertEqual((makefile.default, list(makefile.rules)), ("all", ["all"]))
        self.assertEqual(makefile.variables["HELP"], "usage: make all")

    def test_includes_of_included_makefiles_are_followed(self) -> None:
        files = {
            "Makefile": "include mk/common.mk\n",
            "mk/common.mk": "include mk/lint.mk\n",
            "mk/lint.mk": "lint:\n\tclang-tidy src/a.c\n",
            **github_job("x", "make lint"),
        }
        self.assertEqual(_expanded(_facts(files)), [("clang-tidy", "src/a.c")])

    def test_a_makefile_that_includes_itself_is_read_once_and_says_so(self) -> None:
        files = {
            "Makefile": "include a.mk\nall:\n\techo top\n",
            "a.mk": "include Makefile\n",
            **github_job("x", "make"),
        }
        facts = _facts(files)
        self.assertEqual(_expanded(facts), [("echo", "top")])
        self.assertIn("Makefile includes itself, through Makefile → a.mk", [fact.reason for fact in facts.of(Unknown)])

    def test_a_pattern_rule_covers_the_goals_it_matches_with_their_stem(self) -> None:
        makefile = "lint-%:\n\techo $* $@\n%.check: %.src\n\ttest -f $<\n"
        files = {"Makefile": makefile, **github_job("x", "make lint-docs")}
        self.assertEqual(_expanded(_facts(files)), [("echo", "docs", "lint-docs")])
        for goal in ("lint-", "lintdocs", "other"):
            with self.subTest(goal=goal):
                facts = _facts({"Makefile": makefile, **github_job("x", f"make {goal}")})
                self.assertEqual(_expanded(facts), [])

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

    def test_a_configuration_named_by_either_option_is_read(self) -> None:
        for line in ("pre-commit run --config ci/hooks.yaml", "pre-commit run -c ci/hooks.yaml", "pre-commit run"):
            with self.subTest(line=line):
                facts = _facts({"ci/hooks.yaml": self.CONFIG, **github_job("ubuntu-latest", line)})
                expected = (
                    []
                    if line == "pre-commit run"
                    else [("ruff", "--fix"), ("ruff-format",), ("mypy", "--strict", "src")]
                )
                self.assertEqual(_expanded(facts), expected)

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

    def test_options_that_take_a_value_name_no_hook(self) -> None:
        """fastapi's `prek run --from-ref origin/main --to-ref HEAD` runs every hook: HEAD is the option's value,
        not a hook's id (#221)."""
        every = [("ruff", "--fix"), ("ruff-format",), ("mypy", "--strict", "src")]
        for command in (
            "prek run --from-ref origin/main --to-ref HEAD --show-diff-on-failure",
            "pre-commit run --source origin/main --origin HEAD",
            "pre-commit run -s origin/main -o HEAD",
        ):
            with self.subTest(command=command):
                files = {".pre-commit-config.yaml": self.CONFIG, **github_job("ubuntu-latest", command)}
                self.assertEqual(_expanded(_facts(files)), every)

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

    DEVENV = """\
        { pkgs, ... }:
        {
          git-hooks = {
            package = pkgs.prek;
            hooks = {
              nixfmt = { enable = true; files = "\\\\.nix$"; };
              rustfmt.enable = true;
              markdownlint.enable = false;
              clippy.settings.denyWarnings = true;
            };
          };
        }
        """

    def test_without_a_configuration_the_hooks_devenv_enables_run(self) -> None:
        """devenv writes (and ignores) the configuration from `devenv.nix`'s git-hooks when its shell starts: those it
        enables are what `prek run` runs (cachix/devenv, upstream #285)."""
        cases = {
            "prek run -a": [("nixfmt",), ("rustfmt",)],
            "devenv shell -- prek run -a": [("prek", "run", "-a"), ("nixfmt",), ("rustfmt",)],
            "pre-commit run rustfmt": [("rustfmt",)],
            "SKIP=nixfmt prek run": [("rustfmt",)],
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                facts = _facts({"devenv.nix": self.DEVENV, **github_job("ubuntu-latest", line)})
                self.assertEqual(_expanded(facts), expected)
                self.assertEqual(facts.of(Unknown), ())
        rustfmt = next(command for command in facts.of(Command) if command.argv == ("rustfmt",))
        self.assertEqual(
            (rustfmt.line, rustfmt.origin),
            ("the rustfmt hook of devenv.nix", Origin(path="devenv.nix", at=("git-hooks", "hooks", "rustfmt"))),
        )

    def test_devenvs_older_name_for_its_hooks_is_read(self) -> None:
        devenv = "{ pre-commit.hooks.shellcheck.enable = true; }"
        facts = _facts({"devenv.nix": devenv, **github_job("ubuntu-latest", "pre-commit run -a")})
        self.assertEqual(_expanded(facts), [("shellcheck",)])

    def test_a_committed_or_named_configuration_wins_over_devenv(self) -> None:
        for files, line, expected in (
            ({".pre-commit-config.yaml": self.CONFIG}, "prek run", [("ruff", "--fix"), ("ruff-format",)]),
            ({}, "prek run -c hooks.yaml", []),
        ):
            with self.subTest(line=line):
                facts = _facts({"devenv.nix": self.DEVENV, **files, **github_job("ubuntu-latest", line)})
                self.assertEqual(_expanded(facts)[:2], expected)


TOX_INI = """\
[tox]
env_list =
    lint,
    3.1{2-3}-tests,  # each version
    typing-{mypy,ty}

[testenv]
commands =
    tests: pytest {posargs:-n auto}
    !tests: echo not-tests
    typing-mypy: mypy src \\
        tests
    typing-ty: ty check

[testenv:lint]
commands = ruff check {toxinidir}

[testenv:3.1{2,3}-tests]
commands = coverage run -m pytest
"""


def _tox(files: dict[str, str], line: str) -> list[tuple[str, ...]]:
    commands = _facts({**files, **github_job("ubuntu-latest", line)}).of(Command)
    return [command.argv for command in commands if command.via]


class ToxTests(unittest.TestCase):
    def test_braces_expand_into_alternatives_and_ranges(self) -> None:
        self.assertEqual(braces("py3{11-13}-{a,b}"), [f"py3{n}-{x}" for n in (11, 12, 13) for x in "ab"])

    def test_options_that_take_a_value_name_no_subcommand(self) -> None:
        """black's fuzz workflow runs `tox -e fuzz --result-json $python_ver`: the value is the option's, not a
        subcommand that runs no environment (#199)."""
        for line in ("tox -e lint --result-json 3.11", "tox --hashseed 1 -e lint", "tox --skip-env x -e lint"):
            with self.subTest(line=line):
                self.assertEqual(_tox({"tox.ini": TOX_INI}, line), [("ruff", "check", ".")])

    def test_environments_run_their_own_section_or_the_lines_of_their_factors(self) -> None:
        files = {"tox.ini": TOX_INI}
        cases = {
            "tox -e lint": [("ruff", "check", ".")],
            "tox run -e typing-mypy,typing-ty": [
                ("echo", "not-tests"),
                ("mypy", "src", "tests"),
                ("echo", "not-tests"),
                ("ty", "check"),
            ],
            "tox p -f typing": [
                ("echo", "not-tests"),
                ("mypy", "src", "tests"),
                ("echo", "not-tests"),
                ("ty", "check"),
            ],
            # A factor from a variable matches each section its other parts fit.
            # `coverage run -m pytest` runs pytest.
            "tox run -e $PYTHON-tests": [("coverage", "run", "-m", "pytest"), ("pytest",)],
            "tox list": [],
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual([argv for argv in _tox(files, line) if argv[0] != "tox"], expected)

    def test_without_an_environment_tox_runs_its_env_list(self) -> None:
        found = _tox({"tox.ini": TOX_INI}, "uvx tox")
        self.assertIn(("ruff", "check", "."), found)
        self.assertIn(("coverage", "run", "-m", "pytest"), found)
        self.assertIn(("ty", "check"), found)

    def test_toml_configurations(self) -> None:
        pyproject = '[tool.tox]\nenv_list = ["lint"]\n[tool.tox.env.lint]\ncommands = [["ruff", "check"]]\n'
        self.assertIn(("ruff", "check"), _tox({"pyproject.toml": pyproject}, "tox"))
        toml = '[env_run_base]\ncommands = [["pytest", "{posargs}"]]\n'
        self.assertIn(("pytest", "."), _tox({"tox.toml": toml}, "tox -e py"))

    def test_what_cannot_be_read_is_unknown(self) -> None:
        for files in ({}, {"pyproject.toml": "[project]\n"}, {"tox.ini": "[tox\n"}, {"tox.toml": "env = ["}):
            with self.subTest(files=files):
                unknowns = _facts({**files, **github_job("ubuntu-latest", "tox -e lint")}).of(Unknown)
                # Other readers of a broken tox.ini report it too.
                self.assertIn("the tox environments", [unknown.subject for unknown in unknowns])
        # An environment no section defines runs nothing.
        self.assertEqual(_tox({"tox.ini": "[tox]\nenv_list = a\n"}, "tox"), [])
        self.assertEqual(_tox({"tox.toml": "[env.a]\ndescription = 'x'\n"}, "tox -e a"), [])


class ShellScriptTests(unittest.TestCase):
    SCRIPT: ClassVar[dict[str, str]] = {"ci/lint.sh": "#!/usr/bin/env bash\nset -e\nruff check .\n"}

    def test_a_script_of_the_project_runs_its_commands(self) -> None:
        for line in (
            "bash ci/lint.sh",
            "./ci/lint.sh",
            "sh -e ci/lint.sh",
            "cd ci && ./lint.sh",
            ". ci/lint.sh",
            "source ci/lint.sh",
        ):
            with self.subTest(line=line):
                found = _tox(self.SCRIPT, line)
                self.assertIn(("ruff", "check", "."), found)

    def test_other_files_and_inline_scripts_are_not_followed(self) -> None:
        files = {**self.SCRIPT, "tools/run.py": "print('x')\n", "ci/notes": "ruff check .\n"}
        for line in (
            "bash -c 'echo hi'",
            "./tools/run.py",
            "/usr/bin/env.sh",
            "sh ci/missing.sh",
            "./ci/notes",
            "bash",
        ):
            with self.subTest(line=line):
                self.assertNotIn(("ruff", "check", "."), _tox(files, line))


class CiEnvironmentTests(unittest.TestCase):
    """What a job's environment holds as its steps run, and what its commands' programs are."""

    def _facts(self, *steps: str) -> Facts:
        with temp_project(github_steps(*steps)) as root:
            return make_context(root).facts

    def test_github_env_is_set_for_the_later_steps(self) -> None:
        facts = self._facts('run: echo "CABAL=cabal -v" >> "$GITHUB_ENV"', "run: $CABAL test")
        [command] = [fact for fact in facts.of(Command) if fact.argv[0] == "$CABAL"]
        self.assertEqual(resolved(command), ("cabal", "-v", "test"))
        self.assertFalse([fact for fact in facts.of(Unknown) if "$CABAL" in fact.subject])

    def test_a_word_that_is_one_variable_splits(self) -> None:
        command = Command(
            origin=Origin(path="ci.yml"),
            job="job",
            argv=("$CC", "-c", "x$Y"),
            line="",
            env={"CC": "gcc -m32", "Y": "a b"},
        )
        self.assertEqual(resolved(command), ("gcc", "-m32", "-c", "xa b"))
        # Resolved once, when the command is made; derived, so not recorded among the facts.
        self.assertIs(resolved(command), command.words)
        self.assertNotIn("words", as_dict(command))

    def test_a_program_the_job_does_not_set_is_unknown(self) -> None:
        facts = self._facts("run: $CABAL v2-test all", "run: ${HOME}/bin/tool")
        [unknown] = facts.of(Unknown)
        self.assertIn("$CABAL", unknown.reason)

    def test_a_variable_in_the_programs_name_is_unknown_but_one_in_its_directory_is_not(self) -> None:
        """`$DIR/$TOOL` and `${PREFIX}ruff` run a program whose name is not seen; `${HOME}/bin/tool` runs `tool`."""
        for line, unknown in (
            ("$DIR/$TOOL --lint .", True),
            ("${PREFIX}ruff check .", True),
            ("$DIR/tool", False),
            ("website/version-${{ inputs.version }}/build.sh", False),
            ('"$0" --again', False),
            ('"$BASH" -c true', False),
            ("$_.Name", False),
            ('{"with": {"approved": "${{ true }}"}}', False),
            ("ghostty-${{ needs.setup.outputs.version }}.zip", False),
            ("$PWD/${{ env.EXE }} --test", True),
        ):
            with self.subTest(line=line):
                self.assertEqual(bool(self._facts(f"run: {line}").of(Unknown)), unknown)

    def test_a_program_that_is_an_expression_not_evaluated_is_unknown(self) -> None:
        """`run: ${{ matrix.runs.test }}` with the matrix computed at run time runs what is not seen."""
        workflow = {
            "jobs": {
                "test": {
                    "runs-on": "ubuntu-latest",
                    "strategy": {"matrix": "${{ fromJSON(needs.generate.outputs.strategy) }}"},
                    "steps": [{"run": "${{ matrix.runs.test }}"}],
                }
            }
        }
        with temp_project({GITHUB_WORKFLOW: json.dumps(workflow)}) as root:
            facts = make_context(root).facts
        [unknown] = [unknown for unknown in facts.of(Unknown) if unknown.hides == "commands"]
        self.assertIn("${{ matrix.runs.test }}", unknown.reason)

    def test_a_scripts_constant_assignment_is_resolved(self) -> None:
        """`export PREFIX=""` then `${PREFIX}ruff check .` runs ruff: a value the script sets once, to plain text, is
        put in place in the commands after it (encode/httpx's scripts/check)."""
        for script in ('export PREFIX=""\n${PREFIX}ruff check .', "PREFIX=\n${PREFIX}ruff check ."):
            with self.subTest(script=script):
                facts = self._facts(f"run: |\n  {script.replace(chr(10), chr(10) + '  ')}")
                self.assertIn(("ruff", "check", "."), [resolved(command) for command in facts.of(Command)])
                self.assertFalse(facts.of(Unknown))

    def test_a_variable_assigned_twice_or_from_a_command_is_not_resolved(self) -> None:
        for script in ("T=ruff\nT=black\n$T check .", "T=$(which ruff)\n$T check ."):
            with self.subTest(script=script):
                facts = self._facts(f"run: |\n  {script.replace(chr(10), chr(10) + '  ')}")
                self.assertNotIn(("ruff", "check", "."), [resolved(command) for command in facts.of(Command)])

    def test_scripts_ci_runs_are_held_to_the_same_rule_unless_they_source_others(self) -> None:
        """A repository script's unset program is unknown too; one that sources another file may be set by it."""
        for text, unknown in (('#!/bin/sh\n"$DIR/$TOOL" --lint .\n', True), ("#!/bin/sh\n. ./env.sh\n$CC x\n", False)):
            with self.subTest(text=text):
                files = {"lint.sh": text, "env.sh": "export CC=gcc\n", **github_steps("run: ./lint.sh")}
                with temp_project(files) as root:
                    facts = make_context(root).facts
                self.assertEqual(bool(facts.of(Unknown)), unknown, facts.of(Unknown))

    def test_a_conditional_expression_is_not_a_command(self) -> None:
        """`[[ ... ]]` is a shell keyword, not a command: nothing in it runs, so a variable in it (set by an `eval`
        nothing can read, as in uutils/coreutils' GnuTests.yml) is not an unknown program."""
        for script in (
            'if [[ "$TOTAL" -eq 0 || "$TOTAL" -eq 1 ]]; then exit 1; fi',
            '[[ -n "$NAME" ]] && echo ok',
            'while [[ "$N" -gt 0 ]]; do echo "$N"; done',
        ):
            with self.subTest(script=script):
                self.assertFalse(self._facts(f"run: {script}").of(Unknown))

    def test_a_loop_header_is_not_a_command(self) -> None:
        """`for x in a b; do …; done` and `case $x in` assign and branch; nothing runs a program called `for` or `case`
        (the GitHub Action fixture's composite action)."""
        facts = self._facts(
            "run: for price in 1 2; do total=$((total + price)); done", "run: case $X in a) echo a;; esac"
        )
        self.assertFalse([fact.argv for fact in facts.of(Command) if fact.argv[0] in ("for", "case", "a)")])

    def test_a_program_the_script_sets_is_known(self) -> None:
        for script in ("CC=gcc; $CC -c a.c", "for f in a b; do $f; done", "read -r TOOL; ${TOOL} x"):
            with self.subTest(script=script):
                self.assertFalse(self._facts(f"run: {script}").of(Unknown))
        powershell = github_job("windows-latest", "$tool = 'x'", "$tool --version")
        with temp_project(powershell) as root:
            self.assertFalse(make_context(root).facts.of(Unknown))

    def test_a_variable_carried_to_later_steps_is_set(self) -> None:
        resolvable = self._facts('run: HC=/opt/ghc/bin/ghc-9.8; echo "HC=$HC" >> "$GITHUB_ENV"', "run: $HC --version")
        [command] = [fact for fact in resolvable.of(Command) if fact.argv[0] == "$HC"]
        self.assertEqual(resolved(command), ("/opt/ghc/bin/ghc-9.8", "--version"))
        unresolved = self._facts('run: echo "HC=$(which ghc)" >> "$GITHUB_ENV"', "run: $HC --version")
        self.assertFalse(unresolved.of(Unknown))
