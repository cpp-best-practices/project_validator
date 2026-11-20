"""pixi: the tasks `pixi run <task>` runs, dependencies first, or the program it runs in the environment (#208)."""

from __future__ import annotations

import unittest

from project_validator.facts import Command, Facts, Unknown
from tests.support import github_job, make_context, temp_project

# typst-fletcher's pixi.toml, with the other forms a task takes: a table with dependencies and a directory, a list,
# arguments with defaults, a feature's and a platform's tasks.
PIXI = """\
[project]
name = "fletcher"
channels = ["conda-forge"]

[tasks]
compile = "scripts/compile.nu"
test = "tt run"
check = { cmd = "typos", depends-on = ["compile"] }
docs = { cmd = "typst compile manual.typ", cwd = "docs" }
all = { depends-on = ["check", { task = "test" }] }
words = { cmd = ["typos", "--format", "brief"] }
greet = { cmd = "echo {{ who }} {{ how }}", args = ["who", { arg = "how", default = "loudly" }] }

[feature.lint.tasks]
fmt = "typstyle --check ."

[target.linux-64.tasks]
bench = "hyperfine 'tt run'"
"""


def _run(line: str, files: dict[str, str] | None = None) -> tuple[list[tuple[str, ...]], list[str]]:
    """What `line` runs through pixi (each command's words, and the directory of each that moves), and the subjects
    of what is unknown."""
    with temp_project({"pixi.toml": PIXI, **(files or {}), **github_job("ubuntu-latest", line)}) as root:
        facts: Facts = make_context(root).facts
    commands = [
        (*command.argv, *((f"@{command.directory}",) if command.directory not in (None, ".") else ()))
        for command in facts.of(Command)
        if command.via
    ]
    return commands, [unknown.subject for unknown in facts.of(Unknown)]


class PixiTests(unittest.TestCase):
    def test_a_task_runs_its_command(self) -> None:
        self.assertEqual(_run("pixi run test"), ([("tt", "run")], []))

    def test_dependencies_run_first_each_once(self) -> None:
        self.assertEqual(_run("pixi run check"), ([("scripts/compile.nu",), ("typos",)], []))
        commands, _ = _run("pixi run all")
        self.assertEqual(commands, [("scripts/compile.nu",), ("typos",), ("tt", "run")])

    def test_a_task_runs_in_its_directory(self) -> None:
        self.assertEqual(_run("pixi run docs")[0], [("typst", "compile", "manual.typ", "@docs")])

    def test_a_list_is_one_command(self) -> None:
        self.assertEqual(_run("pixi run words")[0], [("typos", "--format", "brief")])

    def test_arguments_fill_a_tasks_args_or_follow_its_command(self) -> None:
        self.assertEqual(_run("pixi run greet world")[0], [("echo", "world", "loudly")])
        self.assertEqual(_run("pixi run greet world softly")[0], [("echo", "world", "softly")])
        self.assertEqual(_run("pixi run test tests/arrows")[0], [("tt", "run", "tests/arrows")])

    def test_feature_and_platform_tasks_are_tasks(self) -> None:
        self.assertEqual(_run("pixi run -e lint fmt")[0], [("typstyle", "--check", ".")])
        self.assertEqual(_run("pixi run bench")[0], [("hyperfine", "tt run")])

    def test_a_program_that_is_no_task_runs_in_the_environment(self) -> None:
        self.assertEqual(_run("pixi run --frozen pytest -x")[0], [("pytest", "-x")])

    def test_the_tasks_of_a_pyproject(self) -> None:
        pyproject = {"py/pyproject.toml": '[tool.pixi.tasks]\nlint = "ruff check ."\n'}
        self.assertEqual(_run("cd py && pixi run lint", pyproject), ([("ruff", "check", ".", "@py")], []))

    def test_the_manifest_is_found_above_or_named(self) -> None:
        # A task runs where its manifest is, wherever pixi runs.
        self.assertEqual(_run("cd docs && pixi run test", {"docs/x.typ": ""})[0], [("tt", "run")])
        named = {"ci/pixi.toml": '[tasks]\nlint = "ruff check ."\n'}
        self.assertEqual(_run("pixi run --manifest-path ci/pixi.toml lint", named)[0], [("ruff", "check", ".", "@ci")])

    def test_an_unset_argument_is_unknown(self) -> None:
        self.assertEqual(_run("pixi run greet"), ([], ["the pixi task greet"]))

    def test_what_cannot_be_read_runs_as_a_program_or_nothing(self) -> None:
        # A manifest that does not parse, or none at all: the word is a program.
        self.assertEqual(_run("pixi run test", {"pixi.toml": "[tasks\n"})[0], [("test",)])
        with temp_project(github_job("ubuntu-latest", "pixi run lint")) as root:
            commands = [command.argv for command in make_context(root).facts.of(Command) if command.via]
        self.assertEqual(commands, [("lint",)])
        # A value that is no task, an args entry that names nothing, and dependencies that are undefined or circular.
        odd = (
            '[tasks]\nn = 3\na = { cmd = "echo {{ x }}", args = ["x", 7], depends-on = ["b", "zz"] }\n'
            'b = { cmd = "ls", depends-on = "a" }\n'
        )
        self.assertEqual(_run("pixi run a hi", {"pixi.toml": odd}), ([("ls",), ("echo", "hi")], []))
        # `pixi run` alone lists the tasks: nothing runs.
        self.assertEqual(_run("pixi run --frozen"), ([], []))
